"""
Session store — persistent session and task state via SQLite.

Uses a separate connection to the catalog.sqlite database.
Creates its own tables (session_records, task_states) on init.
Does NOT modify existing memory_items/evidence_chunks tables.

All methods return None / empty lists when GA_CONTEXT_RUNTIME_ENABLED != '1'.
"""

import os
import sqlite3
import time
import json
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import _context_enabled


# ── Table DDL (self-managed, not in schema.sql) ──

_SESSION_DDL = """
CREATE TABLE IF NOT EXISTS session_records (
    session_id   TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    started_at   REAL NOT NULL,
    ended_at     REAL,
    last_active_at REAL NOT NULL,
    task_count   INTEGER NOT NULL DEFAULT 0,
    current_active_task_id TEXT,
    last_completed_task_id TEXT
);
"""

_TASK_DDL = """
CREATE TABLE IF NOT EXISTS task_states (
    task_id            TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',
    summary            TEXT NOT NULL DEFAULT '',
    source             TEXT NOT NULL DEFAULT 'user',
    parent_session_id  TEXT NOT NULL,
    project_id         TEXT NOT NULL,
    started_at         REAL,
    completed_at       REAL,
    exit_reason        TEXT,
    turn_count         INTEGER NOT NULL DEFAULT 0,
    tool_count         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_task_states_session ON task_states(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_task_states_project ON task_states(project_id);
CREATE INDEX IF NOT EXISTS idx_task_states_status ON task_states(status);
"""

_SNAPSHOT_DDL = """
CREATE TABLE IF NOT EXISTS session_snapshots (
    session_id              TEXT PRIMARY KEY,
    project_id              TEXT NOT NULL,
    current_mode            TEXT NOT NULL DEFAULT 'idle',
    route_target            TEXT,
    execution_mode          TEXT NOT NULL DEFAULT 'single_agent',
    pending_tool_call       TEXT,
    completed_steps         TEXT NOT NULL DEFAULT '[]',
    pending_steps           TEXT NOT NULL DEFAULT '[]',
    modified_files          TEXT NOT NULL DEFAULT '[]',
    diff_refs               TEXT NOT NULL DEFAULT '[]',
    diagnostic_refs         TEXT NOT NULL DEFAULT '[]',
    review_status           TEXT,
    collaboration_artifacts TEXT NOT NULL DEFAULT '{}',
    event_log_position      INTEGER,
    last_user_intent        TEXT NOT NULL DEFAULT '',
    snapshot_version        INTEGER NOT NULL DEFAULT 1,
    updated_at              REAL NOT NULL,
    metadata                TEXT NOT NULL DEFAULT '{}'
);
"""


def _db_path() -> str | None:
    """Resolve the session DB path from env var, relative to PROJECT_ROOT."""
    import __main__
    raw = os.environ.get("GA_CONTEXT_SESSION_DB", "memory/catalog.sqlite")
    root = getattr(__main__, "PROJECT_ROOT", None) or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    return os.path.join(root, raw)


# ── Dataclasses ──

@dataclass
class TaskState:
    """Persistent state of a single agent task."""

    task_id: str
    run_id: str
    status: str = "pending"
    summary: str = ""
    source: str = "user"
    parent_session_id: str = ""
    project_id: str = ""
    started_at: float | None = None
    completed_at: float | None = None
    exit_reason: str | None = None
    turn_count: int = 0
    tool_count: int = 0

    def __post_init__(self):
        if len(self.summary) > 200:
            self.summary = self.summary[:200]
        VALID_STATUS = {"pending", "running", "completed", "aborted", "error"}
        if self.status not in VALID_STATUS:
            self.status = "pending"


@dataclass
class SessionRecord:
    """Persistent record of an agent session."""

    session_id: str
    project_id: str
    started_at: float
    ended_at: float | None = None
    last_active_at: float = 0.0
    task_count: int = 0
    current_active_task_id: str | None = None
    last_completed_task_id: str | None = None

    def __post_init__(self):
        if self.last_active_at == 0.0:
            self.last_active_at = self.started_at


@dataclass
class SessionSnapshot:
    """Persistent runtime snapshot for stop/restore and memory read-side use."""

    session_id: str
    project_id: str
    current_mode: str = "idle"
    route_target: str | None = None
    execution_mode: str = "single_agent"
    pending_tool_call: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    diff_refs: list[str] = field(default_factory=list)
    diagnostic_refs: list[str] = field(default_factory=list)
    review_status: str | None = None
    collaboration_artifacts: dict = field(default_factory=dict)
    event_log_position: int | None = None
    last_user_intent: str = ""
    snapshot_version: int = 1
    updated_at: float = 0.0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.updated_at == 0.0:
            self.updated_at = time.time()
        self.current_mode = str(self.current_mode or "idle")
        self.execution_mode = str(self.execution_mode or "single_agent")
        if self.snapshot_version < 1:
            self.snapshot_version = 1

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "project_id": self.project_id,
            "current_mode": self.current_mode,
            "route_target": self.route_target,
            "execution_mode": self.execution_mode,
            "pending_tool_call": self.pending_tool_call,
            "completed_steps": list(self.completed_steps),
            "pending_steps": list(self.pending_steps),
            "modified_files": list(self.modified_files),
            "diff_refs": list(self.diff_refs),
            "diagnostic_refs": list(self.diagnostic_refs),
            "review_status": self.review_status,
            "collaboration_artifacts": dict(self.collaboration_artifacts),
            "event_log_position": self.event_log_position,
            "last_user_intent": self.last_user_intent,
            "snapshot_version": self.snapshot_version,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }


# ── Store ──

class SessionStore:
    """Persistent store for session records and task states.

    Thin wrapper over the catalog.sqlite database.
    Creates its own tables on first use.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _db_path()
        self._initialized = False

    # ── Connection management ──

    @contextmanager
    def _conn(self):
        if not self._initialized:
            self._init_tables()
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self):
        """Create session/task tables if they don't exist."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executescript(_SESSION_DDL)
            conn.executescript(_TASK_DDL)
            conn.executescript(_SNAPSHOT_DDL)
            conn.commit()
        finally:
            conn.close()
        self._initialized = True

    # ── Session CRUD ──

    def create_session(self, session_id: str, project_id: str) -> SessionRecord | None:
        """Create a new session record. Returns None when disabled."""
        if not _context_enabled():
            return None
        now = time.time()
        record = SessionRecord(
            session_id=session_id,
            project_id=project_id,
            started_at=now,
            last_active_at=now,
        )
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO session_records
                   (session_id, project_id, started_at, last_active_at, task_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (record.session_id, record.project_id, record.started_at, record.last_active_at, 0),
            )
        return record

    def get_session(self, session_id: str) -> SessionRecord | None:
        """Retrieve a session record by id."""
        if not _context_enabled():
            return None
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM session_records WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return SessionRecord(
            session_id=row["session_id"],
            project_id=row["project_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            last_active_at=row["last_active_at"],
            task_count=row["task_count"],
            current_active_task_id=row["current_active_task_id"],
            last_completed_task_id=row["last_completed_task_id"],
        )

    def update_session(self, record: SessionRecord) -> SessionRecord | None:
        """Update an existing session record."""
        if not _context_enabled():
            return None
        record.last_active_at = time.time()
        with self._conn() as conn:
            conn.execute(
                """UPDATE session_records SET
                   project_id=?, ended_at=?, last_active_at=?, task_count=?,
                   current_active_task_id=?, last_completed_task_id=?
                   WHERE session_id=?""",
                (
                    record.project_id, record.ended_at, record.last_active_at,
                    record.task_count, record.current_active_task_id,
                    record.last_completed_task_id, record.session_id,
                ),
            )
        return record

    # ── Task CRUD ──

    def create_task(self, task: TaskState) -> TaskState | None:
        """Persist a new task state. Returns None when disabled."""
        if not _context_enabled():
            return None
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO task_states
                   (task_id, run_id, status, summary, source, parent_session_id,
                    project_id, started_at, completed_at, exit_reason, turn_count, tool_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task.task_id, task.run_id, task.status, task.summary, task.source,
                    task.parent_session_id, task.project_id, task.started_at,
                    task.completed_at, task.exit_reason, task.turn_count, task.tool_count,
                ),
            )
        return task

    def get_task(self, task_id: str) -> TaskState | None:
        """Retrieve a task state by id."""
        if not _context_enabled():
            return None
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM task_states WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def update_task(self, task: TaskState) -> TaskState | None:
        """Update an existing task state."""
        if not _context_enabled():
            return None
        with self._conn() as conn:
            conn.execute(
                """UPDATE task_states SET
                   status=?, summary=?, completed_at=?, exit_reason=?,
                   turn_count=?, tool_count=?
                   WHERE task_id=?""",
                (
                    task.status, task.summary, task.completed_at, task.exit_reason,
                    task.turn_count, task.tool_count, task.task_id,
                ),
            )
        return task

    def get_active_tasks(self, project_id: str | None = None) -> list[TaskState]:
        """Return all tasks with status 'running', optionally filtered by project_id."""
        if not _context_enabled():
            return []
        with self._conn() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM task_states WHERE status = 'running' AND project_id = ?",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM task_states WHERE status = 'running'"
                ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_last_completed_task(self, session_id: str) -> TaskState | None:
        """Return the most recently completed task for a session."""
        if not _context_enabled():
            return None
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM task_states
                   WHERE parent_session_id = ? AND status IN ('completed', 'aborted', 'error')
                   ORDER BY completed_at DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    # Snapshot CRUD

    def save_snapshot(self, snapshot: SessionSnapshot) -> SessionSnapshot | None:
        """Persist the latest runtime snapshot for a session."""
        if not _context_enabled():
            return None
        snapshot.updated_at = time.time()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO session_snapshots
                   (session_id, project_id, current_mode, route_target, execution_mode,
                    pending_tool_call, completed_steps, pending_steps, modified_files,
                    diff_refs, diagnostic_refs, review_status, collaboration_artifacts,
                    event_log_position, last_user_intent, snapshot_version, updated_at, metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    snapshot.session_id,
                    snapshot.project_id,
                    snapshot.current_mode,
                    snapshot.route_target,
                    snapshot.execution_mode,
                    snapshot.pending_tool_call,
                    json.dumps(snapshot.completed_steps, ensure_ascii=False),
                    json.dumps(snapshot.pending_steps, ensure_ascii=False),
                    json.dumps(snapshot.modified_files, ensure_ascii=False),
                    json.dumps(snapshot.diff_refs, ensure_ascii=False),
                    json.dumps(snapshot.diagnostic_refs, ensure_ascii=False),
                    snapshot.review_status,
                    json.dumps(snapshot.collaboration_artifacts, ensure_ascii=False),
                    snapshot.event_log_position,
                    snapshot.last_user_intent,
                    snapshot.snapshot_version,
                    snapshot.updated_at,
                    json.dumps(snapshot.metadata, ensure_ascii=False),
                ),
            )
        return snapshot

    def get_snapshot(self, session_id: str) -> SessionSnapshot | None:
        """Read the most recent persisted runtime snapshot for a session."""
        if not _context_enabled():
            return None
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM session_snapshots WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def build_recovery_payload(self, session_id: str) -> dict | None:
        """Return a recovery-oriented combined view of session, task, and snapshot state."""
        if not _context_enabled():
            return None
        session = self.get_session(session_id)
        snapshot = self.get_snapshot(session_id)
        last_task = self.get_last_completed_task(session_id)
        if session is None and snapshot is None and last_task is None:
            return None
        return {
            "session": session.__dict__ if session is not None else None,
            "snapshot": snapshot.to_dict() if snapshot is not None else None,
            "last_task": last_task.__dict__ if last_task is not None else None,
        }

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskState:
        return TaskState(
            task_id=row["task_id"],
            run_id=row["run_id"],
            status=row["status"],
            summary=row["summary"],
            source=row["source"],
            parent_session_id=row["parent_session_id"],
            project_id=row["project_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            exit_reason=row["exit_reason"],
            turn_count=row["turn_count"],
            tool_count=row["tool_count"],
        )

    @staticmethod
    def _loads_json(raw: str | None, fallback):
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except Exception:
            return fallback

    @classmethod
    def _row_to_snapshot(cls, row: sqlite3.Row) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=row["session_id"],
            project_id=row["project_id"],
            current_mode=row["current_mode"],
            route_target=row["route_target"],
            execution_mode=row["execution_mode"],
            pending_tool_call=row["pending_tool_call"],
            completed_steps=cls._loads_json(row["completed_steps"], []),
            pending_steps=cls._loads_json(row["pending_steps"], []),
            modified_files=cls._loads_json(row["modified_files"], []),
            diff_refs=cls._loads_json(row["diff_refs"], []),
            diagnostic_refs=cls._loads_json(row["diagnostic_refs"], []),
            review_status=row["review_status"],
            collaboration_artifacts=cls._loads_json(row["collaboration_artifacts"], {}),
            event_log_position=row["event_log_position"],
            last_user_intent=row["last_user_intent"] or "",
            snapshot_version=row["snapshot_version"] or 1,
            updated_at=row["updated_at"] or 0.0,
            metadata=cls._loads_json(row["metadata"], {}),
        )

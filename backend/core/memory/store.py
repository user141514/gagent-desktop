"""Minimal SQLite-backed structured memory store."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .types import EvidenceChunk, MemoryCandidate, MemoryEvent, MemoryItem
from .write_gate import MemoryWriteDecision, MemoryWriteGate


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.schema_path = Path(__file__).with_name("schema.sql")
        self.write_gate = MemoryWriteGate()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        schema_sql = self.schema_path.read_text(encoding="utf-8")
        try:
            with self._connection() as conn:
                conn.executescript(schema_sql)
                self._ensure_schema_compat(conn)
        except sqlite3.OperationalError as exc:
            if "fts5" in str(exc).lower():
                raise RuntimeError(
                    "SQLite FTS5 is required for the structured memory store, but this SQLite build does not support it."
                ) from exc
            raise

    def _ensure_schema_compat(self, conn: sqlite3.Connection) -> None:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(evidence_chunks)").fetchall()
        }
        if "content_hash" not in cols:
            conn.execute("ALTER TABLE evidence_chunks ADD COLUMN content_hash TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_chunks_content_hash ON evidence_chunks(content_hash)"
        )

    def _check_write_gate(
        self,
        *,
        source: str,
        target: str,
        metadata: dict | None = None,
    ) -> MemoryWriteDecision:
        decision = self.write_gate.check_write(source=source, target=target, metadata=metadata)
        if decision.allowed:
            return decision
        raise PermissionError(
            "Memory write denied: "
            f"source='{decision.source}' target='{decision.target}' "
            f"required_redirect='{decision.required_redirect}' "
            f"reason='{decision.reason}'"
        )

    def add_memory_item(
        self,
        *,
        kind: str,
        scope_type: str,
        scope_id: str,
        content: str,
        source: str = "unknown",
        id: str | None = None,
        summary: str | None = None,
        source_path: str | None = None,
        source_turn: str | None = None,
        evidence_chunk_id: str | None = None,
        verified: int | bool = 0,
        confidence: float = 0.5,
        freshness: str | None = None,
        supersedes: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> MemoryItem:
        self._check_write_gate(
            source=source,
            target="memory_items",
            metadata={"kind": kind, "scope_type": scope_type, "scope_id": scope_id},
        )
        timestamp = created_at or _utc_now_iso()
        item = MemoryItem(
            id=id or str(uuid4()),
            kind=kind,
            scope_type=scope_type,
            scope_id=scope_id,
            content=content,
            summary=summary,
            source_path=source_path,
            source_turn=source_turn,
            evidence_chunk_id=evidence_chunk_id,
            verified=int(verified),
            confidence=float(confidence),
            freshness=freshness,
            supersedes=supersedes,
            created_at=timestamp,
            updated_at=updated_at or timestamp,
        )
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (
                    id, kind, scope_type, scope_id, content, summary, source_path,
                    source_turn, evidence_chunk_id, verified, confidence, freshness,
                    supersedes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.kind,
                    item.scope_type,
                    item.scope_id,
                    item.content,
                    item.summary,
                    item.source_path,
                    item.source_turn,
                    item.evidence_chunk_id,
                    item.verified,
                    item.confidence,
                    item.freshness,
                    item.supersedes,
                    item.created_at,
                    item.updated_at,
                ),
            )
        return item

    def add_memory_candidate(
        self,
        *,
        source: str,
        content: str,
        source_id: str | None = None,
        kind: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        evidence_chunk_id: str | None = None,
        confidence: float = 0.5,
        reason: str | None = None,
        status: str = "pending",
        id: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> MemoryCandidate:
        decision = self._check_write_gate(
            source=source,
            target="memory_candidates",
            metadata={"kind": kind, "scope_type": scope_type, "scope_id": scope_id, "status": status},
        )
        timestamp = created_at or _utc_now_iso()
        candidate = MemoryCandidate(
            id=id or str(uuid4()),
            source=decision.source,
            source_id=source_id,
            kind=kind,
            scope_type=scope_type,
            scope_id=scope_id,
            content=content,
            evidence_chunk_id=evidence_chunk_id,
            confidence=float(confidence),
            status=str(status or "pending"),
            reason=reason,
            created_at=timestamp,
            updated_at=updated_at or timestamp,
        )
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_candidates (
                    id, source, source_id, kind, scope_type, scope_id, content,
                    evidence_chunk_id, confidence, status, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.source,
                    candidate.source_id,
                    candidate.kind,
                    candidate.scope_type,
                    candidate.scope_id,
                    candidate.content,
                    candidate.evidence_chunk_id,
                    candidate.confidence,
                    candidate.status,
                    candidate.reason,
                    candidate.created_at,
                    candidate.updated_at,
                ),
            )
        return candidate

    def add_evidence_chunk(
        self,
        *,
        source_path: str,
        content: str,
        source: str = "unknown",
        id: str | None = None,
        source_type: str | None = None,
        actor: str | None = None,
        content_hash: str | None = None,
        summary: str | None = None,
        project_id: str | None = None,
        repo_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        turn_index: int | None = None,
        created_at: str | None = None,
    ) -> EvidenceChunk:
        self._check_write_gate(
            source=source,
            target="evidence_chunks",
            metadata={"source_path": source_path, "source_type": source_type, "actor": actor},
        )
        chunk = EvidenceChunk(
            id=id or str(uuid4()),
            source_path=source_path,
            source_type=source_type,
            actor=actor,
            content=content,
            content_hash=content_hash,
            summary=summary,
            project_id=project_id,
            repo_id=repo_id,
            session_id=session_id,
            run_id=run_id,
            turn_index=turn_index,
            created_at=created_at or _utc_now_iso(),
        )
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO evidence_chunks (
                    id, source_path, source_type, actor, content, content_hash, summary,
                    project_id, repo_id, session_id, run_id, turn_index, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk.id,
                    chunk.source_path,
                    chunk.source_type,
                    chunk.actor,
                    chunk.content,
                    chunk.content_hash,
                    chunk.summary,
                    chunk.project_id,
                    chunk.repo_id,
                    chunk.session_id,
                    chunk.run_id,
                    chunk.turn_index,
                    chunk.created_at,
                ),
            )
            self._insert_evidence_fts(conn, chunk)
        return chunk

    def evidence_chunk_exists(self, source_path: str, content_hash: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM evidence_chunks
                WHERE source_path = ? AND content_hash = ?
                LIMIT 1
                """,
                (source_path, content_hash),
            ).fetchone()
        return row is not None

    def get_evidence_chunk_id(self, source_path: str, content_hash: str) -> str | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM evidence_chunks
                WHERE source_path = ? AND content_hash = ?
                LIMIT 1
                """,
                (source_path, content_hash),
            ).fetchone()
        return row["id"] if row else None

    def add_memory_event(
        self,
        *,
        event_type: str,
        source: str = "unknown",
        id: str | None = None,
        memory_id: str | None = None,
        payload: str | dict | list | None = None,
        created_at: str | None = None,
    ) -> MemoryEvent:
        self._check_write_gate(
            source=source,
            target="memory_events",
            metadata={"event_type": event_type, "memory_id": memory_id},
        )
        payload_text: str | None
        if payload is None or isinstance(payload, str):
            payload_text = payload
        else:
            payload_text = json.dumps(payload, ensure_ascii=False)
        event = MemoryEvent(
            id=id or str(uuid4()),
            memory_id=memory_id,
            event_type=event_type,
            payload=payload_text,
            created_at=created_at or _utc_now_iso(),
        )
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_events (id, memory_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.memory_id,
                    event.event_type,
                    event.payload,
                    event.created_at,
                ),
            )
        return event

    def get_memory_item(self, memory_id: str) -> MemoryItem | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_memory_item(row) if row else None

    def search_evidence_chunks(
        self,
        query: str,
        limit: int = 10,
        *,
        project_id: str | None = None,
        repo_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[EvidenceChunk]:
        if not str(query or "").strip():
            return []
        if limit <= 0:
            return []
        sql = [
            """
            SELECT
                ec.id,
                ec.source_path,
                ec.source_type,
                ec.actor,
                ec.content,
                ec.content_hash,
                ec.summary,
                ec.project_id,
                ec.repo_id,
                ec.session_id,
                ec.run_id,
                ec.turn_index,
                ec.created_at
            FROM evidence_chunks_fts fts
            JOIN evidence_chunks ec ON ec.id = fts.evidence_chunk_id
            WHERE evidence_chunks_fts MATCH ?
            """
        ]
        params: list[object] = [query]
        if project_id is not None:
            sql.append("AND ec.project_id = ?")
            params.append(project_id)
        if repo_id is not None:
            sql.append("AND ec.repo_id = ?")
            params.append(repo_id)
        if session_id is not None:
            sql.append("AND ec.session_id = ?")
            params.append(session_id)
        if run_id is not None:
            sql.append("AND ec.run_id = ?")
            params.append(run_id)
        sql.append("ORDER BY bm25(evidence_chunks_fts), ec.created_at DESC")
        sql.append("LIMIT ?")
        params.append(int(limit))
        try:
            with self._connection() as conn:
                rows = conn.execute("\n".join(sql), params).fetchall()
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "fts5" in message or "no such table: evidence_chunks_fts" in message:
                raise RuntimeError(
                    "SQLite FTS5 search is unavailable. Initialize the database with FTS5 support before searching evidence chunks."
                ) from exc
            raise
        return [self._row_to_evidence_chunk(row) for row in rows]

    def _insert_evidence_fts(self, conn: sqlite3.Connection, chunk: EvidenceChunk) -> None:
        try:
            conn.execute(
                """
                INSERT INTO evidence_chunks_fts (evidence_chunk_id, content, summary, source_path)
                VALUES (?, ?, ?, ?)
                """,
                (
                    chunk.id,
                    chunk.content,
                    chunk.summary or "",
                    chunk.source_path,
                ),
            )
        except sqlite3.OperationalError as exc:
            if "fts5" in str(exc).lower():
                raise RuntimeError(
                    "SQLite FTS5 is required for evidence chunk indexing, but this SQLite build does not support it."
                ) from exc
            raise

    @staticmethod
    def _row_to_memory_item(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            kind=row["kind"],
            scope_type=row["scope_type"],
            scope_id=row["scope_id"],
            content=row["content"],
            summary=row["summary"],
            source_path=row["source_path"],
            source_turn=row["source_turn"],
            evidence_chunk_id=row["evidence_chunk_id"],
            verified=row["verified"],
            confidence=row["confidence"],
            freshness=row["freshness"],
            supersedes=row["supersedes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_evidence_chunk(row: sqlite3.Row) -> EvidenceChunk:
        return EvidenceChunk(
            id=row["id"],
            source_path=row["source_path"],
            source_type=row["source_type"],
            actor=row["actor"],
            content=row["content"],
            content_hash=row["content_hash"] if "content_hash" in row.keys() else None,
            summary=row["summary"],
            project_id=row["project_id"],
            repo_id=row["repo_id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            turn_index=row["turn_index"],
            created_at=row["created_at"],
        )

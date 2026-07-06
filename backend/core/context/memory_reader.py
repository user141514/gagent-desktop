"""
Memory Reader - unified read-only facade for all memory sources.

L1/L2 are PRIMARY (always readable, not gated).
Structured memory is SUPPLEMENTARY (gated by GA_CONTEXT_RUNTIME_ENABLED).
Session/task state is VOLATILE (gated by GA_CONTEXT_RUNTIME_ENABLED).

ContextBuilder MUST consume pre-built MemoryBundle from this reader.
Never reads files or DB directly - that's the reader's job.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session_store import SessionRecord, TaskState, SessionSnapshot

from . import _context_enabled

_PRIORITY_ORDER = {"primary": 0, "supplementary": 1, "volatile": 2}
_PLANE_ORDER = {
    "project_memory": 0,
    "session_memory": 1,
    "run_memory": 2,
    "collaboration_memory": 3,
}


@dataclass
class MemoryBlock:
    """A scoped chunk of memory from any source."""

    source: str
    source_priority: str
    source_path: str | None = None
    content: str = ""
    relevance_score: float = 0.0
    chars: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.chars == 0 and self.content:
            self.chars = len(self.content)
        self.relevance_score = max(0.0, min(1.0, self.relevance_score))


@dataclass
class MemoryBundle:
    """Pre-assembled memory blocks for ContextBuilder consumption."""

    blocks: list[MemoryBlock] = field(default_factory=list)
    total_chars: int = 0
    source_counts: dict = field(default_factory=dict)
    queried_at: float = 0.0

    def __post_init__(self):
        if self.queried_at == 0.0:
            self.queried_at = time.time()
        if self.blocks:
            self.blocks.sort(
                key=lambda b: (_PRIORITY_ORDER.get(b.source_priority, 99), -b.relevance_score)
            )
        if not self.source_counts:
            counts: dict[str, int] = {}
            for block in self.blocks:
                counts[block.source] = counts.get(block.source, 0) + 1
            self.source_counts = counts
        if self.total_chars == 0 and self.blocks:
            self.total_chars = sum(block.chars for block in self.blocks)


@dataclass
class MemoryPlane:
    """Runtime-facing memory plane contract."""

    plane: str
    description: str
    scope: str
    default_sources: list[str] = field(default_factory=list)
    write_policy: str = "read_only"
    active_in_modes: list[str] = field(default_factory=list)


@dataclass
class MemoryPlaneReport:
    """Structured view of runtime memory planes and current attachments."""

    planes: list[MemoryPlane] = field(default_factory=list)
    attachments: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self):
        self.planes.sort(key=lambda plane: _PLANE_ORDER.get(plane.plane, 99))


class MemoryReader:
    """Unified read-only facade for all memory sources."""

    def __init__(self, project_root: str | None = None, db_path: str | None = None):
        self._project_root = project_root or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        self._db_path = db_path

    def read_global_memory(self) -> dict[str, str]:
        """Return {l1: str, l2: str}. L1/L2 are always available."""
        memory_dir = os.path.join(self._project_root, "memory")
        result: dict[str, str] = {}

        for filename, key in [
            ("global_mem_insight.txt", "l1"),
            ("global_mem.txt", "l2"),
        ]:
            path = os.path.join(memory_dir, filename)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    result[key] = handle.read()
            except FileNotFoundError:
                result[key] = ""

        return result

    def read_global_memory_blocks(self) -> list[MemoryBlock]:
        """Read L1/L2 as MemoryBlock list with primary priority."""
        mem = self.read_global_memory()
        blocks: list[MemoryBlock] = []

        if mem.get("l1"):
            blocks.append(MemoryBlock(
                source="L1",
                source_priority="primary",
                source_path=os.path.join(self._project_root, "memory", "global_mem_insight.txt"),
                content=mem["l1"],
                relevance_score=1.0,
            ))

        if mem.get("l2"):
            blocks.append(MemoryBlock(
                source="L2",
                source_priority="primary",
                source_path=os.path.join(self._project_root, "memory", "global_mem.txt"),
                content=mem["l2"],
                relevance_score=0.9,
            ))

        return blocks

    def read_structured_memory(self, query: str, limit: int = 5) -> list[MemoryBlock]:
        """FTS5 search in structured memory. Returns supplementary blocks."""
        if not _context_enabled():
            return []

        db_path = self._db_path or os.path.join(self._project_root, "memory", "catalog.sqlite")
        if not os.path.exists(db_path):
            return []

        try:
            from core.memory.store import MemoryStore
            store = MemoryStore(db_path)
            results = store.search_evidence_chunks(query, limit=limit)
        except Exception:
            return []

        blocks: list[MemoryBlock] = []
        for chunk in results:
            content = getattr(chunk, "content", "") or ""
            blocks.append(MemoryBlock(
                source="structured:supplementary",
                source_priority="supplementary",
                source_path=f"sqlite://{db_path}#{getattr(chunk, 'id', '')}",
                content=content,
                relevance_score=0.5,
                metadata={
                    "chunk_id": getattr(chunk, "id", ""),
                    "session_id": getattr(chunk, "session_id", None),
                    "project_id": getattr(chunk, "project_id", None),
                    "run_id": getattr(chunk, "run_id", None),
                    "turn_index": getattr(chunk, "turn_index", None),
                },
            ))

        return blocks

    def read_session_state(self, session_id: str) -> "SessionRecord | None":
        """Read session record from SessionStore."""
        if not _context_enabled():
            return None
        try:
            from .session_store import SessionStore
            store = SessionStore(db_path=self._db_path)
            return store.get_session(session_id)
        except Exception:
            return None

    def read_task_state(self, task_id: str) -> "TaskState | None":
        """Read task state from SessionStore."""
        if not _context_enabled():
            return None
        try:
            from .session_store import SessionStore
            store = SessionStore(db_path=self._db_path)
            return store.get_task(task_id)
        except Exception:
            return None

    def read_active_tasks(self, project_id: str | None = None) -> list["TaskState"]:
        """Read active (running) tasks from SessionStore."""
        if not _context_enabled():
            return []
        try:
            from .session_store import SessionStore
            store = SessionStore(db_path=self._db_path)
            return store.get_active_tasks(project_id=project_id)
        except Exception:
            return []

    def read_session_snapshot(self, session_id: str) -> "SessionSnapshot | None":
        """Read the persisted runtime snapshot for a session."""
        if not _context_enabled():
            return None
        try:
            from .session_store import SessionStore
            store = SessionStore(db_path=self._db_path)
            return store.get_snapshot(session_id)
        except Exception:
            return None

    def read_session_history(self, session_id: str, limit: int = 10) -> list[MemoryBlock]:
        """Read recent completed tasks for a session as volatile memory blocks."""
        if not _context_enabled():
            return []
        try:
            from .session_store import SessionStore
            store = SessionStore(db_path=self._db_path)
            last = store.get_last_completed_task(session_id)
            if last and last.summary:
                return [MemoryBlock(
                    source="task",
                    source_priority="volatile",
                    content=f"Last task: {last.summary} [{last.status}]",
                    relevance_score=0.7,
                    metadata={"task_id": last.task_id, "status": last.status},
                )]
        except Exception:
            pass
        return []

    def read_session_snapshot_block(self, session_id: str) -> MemoryBlock | None:
        """Render the latest runtime snapshot as a volatile memory block."""
        snapshot = self.read_session_snapshot(session_id)
        if snapshot is None:
            return None

        summary_lines = [
            f"Mode: {snapshot.current_mode}",
            f"Execution mode: {snapshot.execution_mode}",
        ]
        if snapshot.route_target:
            summary_lines.append(f"Route target: {snapshot.route_target}")
        if snapshot.pending_tool_call:
            summary_lines.append(f"Pending tool: {snapshot.pending_tool_call}")
        if snapshot.last_user_intent:
            summary_lines.append(f"Last intent: {snapshot.last_user_intent}")
        if snapshot.pending_steps:
            summary_lines.append("Pending steps: " + "; ".join(snapshot.pending_steps[:5]))
        if snapshot.completed_steps:
            summary_lines.append("Completed steps: " + "; ".join(snapshot.completed_steps[:5]))
        if snapshot.modified_files:
            summary_lines.append("Modified files: " + ", ".join(snapshot.modified_files[:5]))
        if snapshot.review_status:
            summary_lines.append(f"Review status: {snapshot.review_status}")
        if snapshot.collaboration_artifacts:
            summary_lines.append(
                "Collaboration artifacts: " + ", ".join(sorted(snapshot.collaboration_artifacts.keys())[:5])
            )

        return MemoryBlock(
            source="session:snapshot",
            source_priority="volatile",
            source_path=f"sqlite://{self._db_path or ''}#session_snapshots/{session_id}",
            content="\n".join(summary_lines),
            relevance_score=0.95,
            metadata={
                "session_id": snapshot.session_id,
                "current_mode": snapshot.current_mode,
                "execution_mode": snapshot.execution_mode,
                "review_status": snapshot.review_status,
                "snapshot_version": snapshot.snapshot_version,
            },
        )

    def describe_memory_planes(self, session_id: str | None = None) -> MemoryPlaneReport:
        """Return the memory plane contract for the current runtime design."""
        attachments: dict[str, dict] = {}
        if session_id:
            snapshot = self.read_session_snapshot(session_id)
            if snapshot is not None:
                attachments["session_memory"] = {
                    "session_id": snapshot.session_id,
                    "current_mode": snapshot.current_mode,
                    "execution_mode": snapshot.execution_mode,
                    "has_collaboration_artifacts": bool(snapshot.collaboration_artifacts),
                }

        return MemoryPlaneReport(
            planes=[
                MemoryPlane(
                    plane="project_memory",
                    description="Durable project facts and rules.",
                    scope="project",
                    default_sources=["L1", "L2", "structured:supplementary"],
                    write_policy="host_promoted_only",
                    active_in_modes=["direct_answer", "plan", "code", "diagnose", "review", "recovery"],
                ),
                MemoryPlane(
                    plane="session_memory",
                    description="Session progress, mode, and recovery state.",
                    scope="session",
                    default_sources=["session:snapshot", "task"],
                    write_policy="runtime_host_only",
                    active_in_modes=["plan", "code", "diagnose", "review", "recovery", "stopped"],
                ),
                MemoryPlane(
                    plane="run_memory",
                    description="Transient per-run working context and recent turns.",
                    scope="run",
                    default_sources=["recent_turns", "working_memory"],
                    write_policy="executor_only",
                    active_in_modes=["direct_answer", "plan", "code", "diagnose", "review"],
                ),
                MemoryPlane(
                    plane="collaboration_memory",
                    description="Shared artifacts for multi-agent collaboration.",
                    scope="run",
                    default_sources=["shared_artifact_store"],
                    write_policy="multi_agent_only",
                    active_in_modes=["code", "review", "diagnose"],
                ),
            ],
            attachments=attachments,
        )

    def scoped_query(
        self,
        user_query: str = "",
        project_id: str | None = None,
        session_id: str | None = None,
        max_chars: int = 2000,
    ) -> MemoryBundle:
        """Assemble a MemoryBundle from all sources, respecting priority order."""
        blocks: list[MemoryBlock] = []
        budget = max_chars

        primary_blocks = self.read_global_memory_blocks()
        for block in primary_blocks:
            if block.chars <= budget:
                blocks.append(block)
                budget -= block.chars
            else:
                blocks.append(MemoryBlock(
                    source=block.source,
                    source_priority=block.source_priority,
                    source_path=block.source_path,
                    content=block.content[:budget],
                    relevance_score=block.relevance_score,
                    metadata=block.metadata,
                ))
                budget = 0

        if budget > 50 and user_query:
            structured_blocks = self.read_structured_memory(user_query, limit=5)
            for block in structured_blocks:
                if budget <= 50:
                    break
                content = block.content
                if len(content) > budget:
                    content = content[:budget] + "..."
                blocks.append(MemoryBlock(
                    source=block.source,
                    source_priority=block.source_priority,
                    source_path=block.source_path,
                    content=content,
                    relevance_score=block.relevance_score,
                    metadata=block.metadata,
                ))
                budget -= len(content)

        if budget > 50 and session_id:
            snapshot_block = self.read_session_snapshot_block(session_id)
            if snapshot_block is not None and budget > 50:
                snapshot_content = snapshot_block.content
                if len(snapshot_content) > budget:
                    snapshot_content = snapshot_content[:budget] + "..."
                blocks.append(MemoryBlock(
                    source=snapshot_block.source,
                    source_priority=snapshot_block.source_priority,
                    source_path=snapshot_block.source_path,
                    content=snapshot_content,
                    relevance_score=snapshot_block.relevance_score,
                    metadata=snapshot_block.metadata,
                ))
                budget -= len(snapshot_content)

            session_blocks = self.read_session_history(session_id, limit=5)
            for block in session_blocks:
                if budget <= 50:
                    break
                content = block.content
                if len(content) > budget:
                    content = content[:budget] + "..."
                blocks.append(MemoryBlock(
                    source=block.source,
                    source_priority=block.source_priority,
                    source_path=block.source_path,
                    content=content,
                    relevance_score=block.relevance_score,
                    metadata=block.metadata,
                ))
                budget -= len(content)

        blocks.sort(key=lambda b: (_PRIORITY_ORDER.get(b.source_priority, 99), -b.relevance_score))

        counts: dict[str, int] = {}
        for block in blocks:
            counts[block.source] = counts.get(block.source, 0) + 1

        return MemoryBundle(
            blocks=blocks,
            total_chars=sum(block.chars for block in blocks),
            source_counts=counts,
            queried_at=time.time(),
        )


_STRUCTURED_MEMORY_ENV_VAR = "GENERIC_AGENT_STRUCTURED_MEMORY"


def _structured_memory_enabled() -> bool:
    return os.environ.get(_STRUCTURED_MEMORY_ENV_VAR, "").strip() == "1"


def structured_memory_enabled() -> bool:
    return _structured_memory_enabled()


def read_global_memory(project_root: str | None = None) -> dict:
    """Standalone wrapper matching the legacy reader API."""
    reader = MemoryReader(project_root=project_root)
    raw = reader.read_global_memory()
    result: dict = {
        "global_mem_insight": raw.get("l1"),
        "global_mem": raw.get("l2"),
        "sources": [],
        "total_chars": 0,
    }
    memory_dir = os.path.join(reader._project_root, "memory")
    if raw.get("l1"):
        chars = len(raw["l1"])
        result["sources"].append(
            {"file": os.path.join(memory_dir, "global_mem_insight.txt"), "label": "L1", "chars": chars}
        )
        result["total_chars"] += chars
    if raw.get("l2"):
        chars = len(raw["l2"])
        result["sources"].append(
            {"file": os.path.join(memory_dir, "global_mem.txt"), "label": "L2", "chars": chars}
        )
        result["total_chars"] += chars
    return result


def search_structured_memory(
    query: str,
    db_path: str | None = None,
    limit: int = 5,
) -> dict:
    """Standalone wrapper matching the legacy reader API."""
    if not _structured_memory_enabled():
        return {"results": [], "total_hits": 0, "error": None, "disabled": True}

    reader = MemoryReader(db_path=db_path)
    blocks = reader.read_structured_memory(query, limit=limit)
    results = [
        {
            "source_path": block.source_path or "",
            "summary": block.metadata.get("chunk_id", ""),
            "content_preview": (block.content or "")[:500],
            "created_at": block.metadata.get("created_at", ""),
        }
        for block in blocks
    ]
    return {"results": results, "total_hits": len(results), "error": None, "disabled": False}


def read_working_memory(history: list[str], max_items: int = 20) -> str:
    """Standalone wrapper matching the legacy reader API."""
    if not history:
        return ""
    h_str = "\n".join(history[-max_items:])
    return (
        "### [WORKING MEMORY]\n"
        f"<history>\n{h_str}\n</history>\n"
        "Use this as compressed recent context. Keep the next <summary> consistent with it."
    )


def build_memory_source_report() -> dict:
    """Standalone wrapper matching the legacy reader API."""
    reader = MemoryReader()
    global_mem = reader.read_global_memory()
    l1_chars = len(global_mem.get("l1") or "")
    l2_chars = len(global_mem.get("l2") or "")
    return {
        "l1_chars": l1_chars,
        "l2_chars": l2_chars,
        "structured_enabled": _structured_memory_enabled(),
        "total_sources": (1 if l1_chars > 0 else 0) + (1 if l2_chars > 0 else 0),
    }

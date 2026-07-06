"""
Context Builder — pure constructor. Takes typed dataclasses, returns ContextPacket.

NEVER reads files. NEVER reads SQLite. NEVER reads global memory directly.
All memory content arrives via MemoryBundle from MemoryReader.

M4: Added recent_turns and working_memory as first-class source types.
    Preview mode writes ContextPacket as JSON to temp/context_audit/.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .workspace_probe import WorkspaceSnapshot
    from .project_identity import ProjectIdentity
    from .runtime_identity import RuntimeIdentity
    from .session_store import SessionRecord, TaskState
    from .memory_reader import MemoryBundle

# ── Route budgets ──

_ROUTE_BUDGET: dict[str | None, dict[str, int]] = {
    "chat":            {"workspace": 0,   "project": 0,   "state": 0,   "memory": 0,    "recent_turns": 0,    "working_memory": 0},
    "code":            {"workspace": 150, "project": 150,  "state": 500, "memory": 1500, "recent_turns": 1200, "working_memory": 1000},
    "review":          {"workspace": 150, "project": 150,  "state": 500, "memory": 1500, "recent_turns": 1200, "working_memory": 1000},
    "research":        {"workspace": 150, "project": 150,  "state": 300, "memory": 2500, "recent_turns": 1200, "working_memory": 1000},
    "executor":        {"workspace": 150, "project": 150,  "state": 500, "memory": 3000, "recent_turns": 1200, "working_memory": 1200},
    "planner_executor": {"workspace": 150, "project": 150, "state": 500, "memory": 3000, "recent_turns": 1200, "working_memory": 1200},
    None:              {"workspace": 0,   "project": 0,   "state": 0,   "memory": 0,    "recent_turns": 0,    "working_memory": 0},
}

# Truncation order when over budget: volatile → supplementary → state blocks.
# Identity blocks (workspace, project) are never truncated — they are tiny.
# Conversation blocks (recent_turns, working_memory) are truncated before memory.

# Preview output directory (relative to project root)
_PREVIEW_DIR = "temp/context_audit"
_TRUNCATION_MARKER = "\n[truncated]"
_TEXT_BLOCK_ORDER = (
    "workspace",
    "project",
    "state",
    "memory",
    "recent_turns",
    "working_memory",
)
_TOTAL_TRIM_ORDER = (
    "working_memory",
    "recent_turns",
    "memory",
    "state",
    "project",
    "workspace",
)


def _truncate_text(text: str, max_chars: int) -> str:
    limit = max(int(max_chars or 0), 0)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(_TRUNCATION_MARKER):
        return text[:limit]
    return text[: limit - len(_TRUNCATION_MARKER)].rstrip() + _TRUNCATION_MARKER


def _fit_text_blocks_to_total_budget(blocks: dict[str, str], max_chars: int) -> dict[str, str]:
    """Trim low-signal blocks until the packet honors the total budget."""
    limit = max(int(max_chars or 0), 0)
    fitted = {key: str(blocks.get(key) or "") for key in _TEXT_BLOCK_ORDER}
    total = sum(len(value) for value in fitted.values())
    if total <= limit:
        return fitted

    for key in _TOTAL_TRIM_ORDER:
        if total <= limit:
            break
        current = fitted.get(key, "")
        if not current:
            continue
        overflow = total - limit
        target_len = max(len(current) - overflow, 0)
        trimmed = _truncate_text(current, target_len)
        fitted[key] = trimmed
        total -= len(current) - len(trimmed)
    return fitted


@dataclass
class ContextPacket:
    """Assembled context for agent injection."""

    workspace: "WorkspaceSnapshot | None" = None
    project: "ProjectIdentity | None" = None
    runtime: "RuntimeIdentity | None" = None
    current_session: "SessionRecord | None" = None
    last_active_task: "TaskState | None" = None
    active_tasks: list = field(default_factory=list)
    memory_bundle: "MemoryBundle | None" = None
    recent_turns_block: str = ""          # M4: from build_recent_conversation_block()
    working_memory_block: str = ""        # M4: from _working_memory_message()
    workspace_block: str = ""
    project_block: str = ""
    state_block: str = ""
    memory_block: str = ""
    generated_at: float = 0.0
    total_chars: int = 0
    source_breakdown: dict[str, int] = field(default_factory=dict)
    policy_mode: str = "preview"
    target_route: str | None = None
    max_chars_limit: int = 4000

    def __post_init__(self):
        if self.generated_at == 0.0:
            self.generated_at = time.time()

    def to_dict(self) -> dict:
        """Serialize to dict for JSON preview export."""
        return {
            "generated_at": self.generated_at,
            "target_route": self.target_route,
            "policy_mode": self.policy_mode,
            "total_chars": self.total_chars,
            "max_chars_limit": self.max_chars_limit,
            "source_breakdown": self.source_breakdown,
            "workspace": {
                "cwd": self.workspace.cwd,
                "git_root": self.workspace.git_root,
                "git_branch": self.workspace.git_branch,
                "dirty": self.workspace.has_uncommitted_changes,
                "dirty_files": self.workspace.dirty_files[:10],
            } if self.workspace else None,
            "project": {
                "project_id": self.project.project_id,
                "name": self.project.project_name,
                "root": self.project.project_root,
                "key_files": self.project.key_files[:10],
                "languages": self.project.languages,
            } if self.project else None,
            "runtime": {
                "session_id": self.runtime.session_id,
                "backend": self.runtime.agent_backend,
            } if self.runtime else None,
            "session": {
                "tasks": self.current_session.task_count,
                "last_completed": self.current_session.last_completed_task_id,
            } if self.current_session else None,
            "last_task": {
                "summary": self.last_active_task.summary,
                "status": self.last_active_task.status,
            } if self.last_active_task else None,
            "active_tasks": [
                {"summary": t.summary, "status": t.status}
                for t in self.active_tasks[:5]
            ],
            "memory_blocks": [
                {
                    "source": b.source,
                    "priority": b.source_priority,
                    "score": b.relevance_score,
                    "chars": b.chars,
                }
                for b in (self.memory_bundle.blocks if self.memory_bundle else [])
            ],
            "recent_turns_chars": len(self.recent_turns_block),
            "working_memory_chars": len(self.working_memory_block),
        }


class ContextBuilder:
    """Pure constructor for ContextPacket.

    Usage:
        builder = ContextBuilder(max_chars=4000, policy_mode="preview")
        packet = builder.build(
            workspace=snap, project=pid, runtime=rt,
            session=rec, memory_bundle=bundle,
            target_route="code",
        )
    """

    def __init__(self, *, max_chars: int = 4000, policy_mode: str = "preview"):
        self._max_chars = max_chars
        self._policy_mode = policy_mode

    # ── Public API ──

    def build(
        self,
        *,
        workspace: "WorkspaceSnapshot | None" = None,
        project: "ProjectIdentity | None" = None,
        runtime: "RuntimeIdentity | None" = None,
        session: "SessionRecord | None" = None,
        last_task: "TaskState | None" = None,
        active_tasks: list | None = None,
        memory_bundle: "MemoryBundle | None" = None,
        recent_turns_block: str = "",            # M4: pre-built by caller via build_recent_conversation_block()
        working_memory_block: str = "",          # M4: pre-built by caller via _working_memory_message()
        target_route: str | None = None,
    ) -> ContextPacket | None:
        """Build a ContextPacket. Returns None when:
        - policy_mode == 'off'
        - target_route is None or 'chat' (no injection for casual conversation)
        """
        if self._policy_mode == "off":
            return None
        if target_route is None or target_route == "chat":
            return None

        budget = _ROUTE_BUDGET.get(target_route, _ROUTE_BUDGET[None])
        workspace_chars = budget.get("workspace", 0)
        project_chars = budget.get("project", 0)
        state_chars = budget.get("state", 0)
        memory_chars = budget.get("memory", 0)
        recent_turns_chars = budget.get("recent_turns", 0)
        working_memory_chars = budget.get("working_memory", 0)

        # ── Workspace block (never truncated, small) ──
        ws_text = self._format_workspace(workspace) if workspace and workspace_chars > 0 else ""
        ws_text = ws_text[:workspace_chars] if workspace_chars > 0 else ""

        # ── Project block ──
        pr_text = self._format_project(project) if project and project_chars > 0 else ""
        pr_text = pr_text[:project_chars] if project_chars > 0 else ""

        # ── State block ──
        st_text = self._format_state(session, last_task, active_tasks) if state_chars > 0 else ""
        st_text = st_text[:state_chars] if state_chars > 0 else ""

        # ── Memory block ──
        mem_text = self._format_memory(memory_bundle, memory_chars) if memory_bundle and memory_chars > 0 else ""

        # ── Recent turns block (M4) ──
        rt_text = recent_turns_block[:recent_turns_chars] if recent_turns_block and recent_turns_chars > 0 else ""

        # ── Working memory block (M4) ──
        wm_text = working_memory_block[:working_memory_chars] if working_memory_block and working_memory_chars > 0 else ""

        text_blocks = _fit_text_blocks_to_total_budget(
            {
                "workspace": ws_text,
                "project": pr_text,
                "state": st_text,
                "memory": mem_text,
                "recent_turns": rt_text,
                "working_memory": wm_text,
            },
            self._max_chars,
        )
        breakdown = {key: len(text_blocks[key]) for key in _TEXT_BLOCK_ORDER}
        total = sum(breakdown.values())

        return ContextPacket(
            workspace=workspace,
            project=project,
            runtime=runtime,
            current_session=session,
            last_active_task=last_task,
            active_tasks=active_tasks or [],
            memory_bundle=memory_bundle,
            recent_turns_block=text_blocks["recent_turns"],
            working_memory_block=text_blocks["working_memory"],
            workspace_block=text_blocks["workspace"],
            project_block=text_blocks["project"],
            state_block=text_blocks["state"],
            memory_block=text_blocks["memory"],
            generated_at=time.time(),
            total_chars=total,
            source_breakdown=breakdown,
            policy_mode=self._policy_mode,
            target_route=target_route,
            max_chars_limit=self._max_chars,
        )

    def preview_to_disk(
        self,
        packet: ContextPacket,
        project_root: str | None = None,
    ) -> str | None:
        """Write ContextPacket as JSON to temp/context_audit/ for inspection.

        Returns the output file path, or None if preview mode is not active.
        Does NOT inject context into any runtime path.
        """
        if self._policy_mode != "preview":
            return None

        root = project_root or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        audit_dir = os.path.join(root, _PREVIEW_DIR)
        os.makedirs(audit_dir, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        route = packet.target_route or "unknown"
        filename = f"context_packet_{route}_{timestamp}.json"
        filepath = os.path.join(audit_dir, filename)

        payload = packet.to_dict()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)

        return filepath

    def serialize(self, packet: ContextPacket) -> str:
        """Render a ContextPacket to the injection text format."""
        if packet is None:
            return ""

        parts: list[str] = []
        parts.append(
            f"[CONTEXT PACKET - {packet.policy_mode} mode, "
            f"{packet.total_chars} chars, route={packet.target_route}]"
        )

        if packet.workspace_block:
            parts.append("\n## Workspace")
            parts.append(packet.workspace_block)

        if packet.project_block:
            parts.append("\n## Project")
            parts.append(packet.project_block)

        rt = packet.runtime
        if rt:
            parts.append("\n## Runtime")
            parts.append(f"session_id: {rt.session_id}")
            parts.append(f"backend: {rt.agent_backend}")

        if packet.state_block:
            parts.append("\n## Session")
            parts.append(packet.state_block)

        if packet.memory_block:
            parts.append("\n## Relevant Memory")
            parts.append(packet.memory_block)

        # M4: Recent turns block
        if packet.recent_turns_block:
            parts.append("\n## Recent Conversation")
            parts.append(packet.recent_turns_block)

        # M4: Working memory block
        if packet.working_memory_block:
            parts.append("\n## Working Memory")
            parts.append(packet.working_memory_block)

        parts.append("\n[/CONTEXT PACKET]")
        return "\n".join(parts)

    # ── Format helpers ──

    @staticmethod
    def _format_workspace(ws: "WorkspaceSnapshot") -> str:
        lines = [f"cwd: {ws.cwd}"]
        if ws.git_root:
            lines.append(f"git_root: {ws.git_root}")
            if ws.git_branch:
                lines.append(f"branch: {ws.git_branch}")
            lines.append(f"dirty: {ws.has_uncommitted_changes}")
            if ws.dirty_files:
                lines.append(f"changed: {', '.join(ws.dirty_files[:10])}")
        return "\n".join(lines)

    @staticmethod
    def _format_project(pr: "ProjectIdentity") -> str:
        lines = [
            f"project_id: {pr.project_id}",
            f"name: {pr.project_name}",
            f"root: {pr.project_root}",
        ]
        if pr.key_files:
            lines.append(f"key_files: {', '.join(pr.key_files[:10])}")
        if pr.languages:
            lines.append(f"languages: {', '.join(pr.languages)}")
        return "\n".join(lines)

    @staticmethod
    def _format_state(
        session: "SessionRecord | None",
        last_task: "TaskState | None",
        active_tasks: list | None,
    ) -> str:
        lines: list[str] = []
        if session:
            lines.append(f"session: {session.session_id} ({session.task_count} tasks)")
            if session.current_active_task_id:
                lines.append(f"active_task: {session.current_active_task_id}")
        if last_task:
            lines.append(f"last_task: {last_task.summary} [{last_task.status}]")
        if active_tasks:
            for t in active_tasks[:5]:
                lines.append(f"  - {t.summary} [{t.status}]")
        return "\n".join(lines)

    @staticmethod
    def _format_memory(bundle: "MemoryBundle", max_chars: int) -> str:
        if not bundle or not bundle.blocks:
            return ""
        parts: list[str] = []
        budget = max_chars
        for b in bundle.blocks:
            if budget <= 0:
                break
            header = f"[{b.source} | priority={b.source_priority} | score={b.relevance_score:.2f}]"
            if len(header) + 1 >= budget:
                parts.append(_truncate_text(header, budget))
                break
            parts.append(header)
            budget -= len(header) + 1
            content = b.content
            if len(content) > budget:
                content = _truncate_text(content, budget)
            parts.append(content)
            budget -= len(content) + 1
        return "\n".join(parts)

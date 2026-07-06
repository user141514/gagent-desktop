from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context.session_store import SessionSnapshot


@dataclass
class RuntimeSessionState:
    """In-memory runtime session state mirrored into persistent snapshots."""

    session_id: str
    project_id: str
    current_mode: str = "idle"
    route_target: str | None = None
    execution_mode: str = "single_agent"
    turn_id: int = 0
    step_id: int = 0
    pending_tool_call: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    diff_refs: list[str] = field(default_factory=list)
    diagnostic_refs: list[str] = field(default_factory=list)
    review_status: str | None = None
    collaboration_artifacts: dict[str, Any] = field(default_factory=dict)
    event_log_position: int = 0
    last_user_intent: str = ""
    status: str = "running"
    last_error: str = ""

    def advance_step(self) -> int:
        self.step_id += 1
        return self.step_id

    def advance_turn(self) -> int:
        self.turn_id += 1
        return self.turn_id

    def set_pending_steps(self, steps: list[str]) -> None:
        self.pending_steps = list(steps)

    def add_completed_step(self, step: str) -> None:
        step = str(step or "").strip()
        if step:
            self.completed_steps.append(step)

    def merge_modified_files(self, files: list[str] | None) -> None:
        for file_path in files or []:
            if file_path and file_path not in self.modified_files:
                self.modified_files.append(file_path)

    def merge_diff_refs(self, refs: list[str] | None) -> None:
        for diff_ref in refs or []:
            if diff_ref and diff_ref not in self.diff_refs:
                self.diff_refs.append(diff_ref)

    def merge_diagnostic_refs(self, refs: list[str] | None) -> None:
        for diagnostic_ref in refs or []:
            if diagnostic_ref and diagnostic_ref not in self.diagnostic_refs:
                self.diagnostic_refs.append(diagnostic_ref)

    def sync_collaboration_artifacts(self, artifacts: dict[str, Any] | None) -> None:
        if artifacts:
            self.collaboration_artifacts = dict(artifacts)

    def to_snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=self.session_id,
            project_id=self.project_id,
            current_mode=self.current_mode,
            route_target=self.route_target,
            execution_mode=self.execution_mode,
            pending_tool_call=self.pending_tool_call,
            completed_steps=list(self.completed_steps),
            pending_steps=list(self.pending_steps),
            modified_files=list(self.modified_files),
            diff_refs=list(self.diff_refs),
            diagnostic_refs=list(self.diagnostic_refs),
            review_status=self.review_status,
            collaboration_artifacts=dict(self.collaboration_artifacts),
            event_log_position=self.event_log_position,
            last_user_intent=self.last_user_intent,
            metadata={"status": self.status, "last_error": self.last_error},
        )

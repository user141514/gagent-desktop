from __future__ import annotations

import os
import uuid
from typing import Any

from core.context.session_store import SessionRecord, SessionStore, TaskState

from .event_log import RuntimeEventLog
from .event_schema import RuntimeEvent
from .session import RuntimeSessionState
from .state_machine import IllegalModeTransition, ModeStateMachine, mode_for_route


def _default_project_id(project_root: str) -> str:
    name = os.path.basename(os.path.abspath(project_root)).strip() or "genericagent"
    return name.replace(" ", "_").lower()


class RuntimeHost:
    """Central runtime control plane for mode, events, and snapshot persistence."""

    def __init__(
        self,
        *,
        project_root: str,
        project_id: str | None = None,
        logs_root: str | None = None,
        session_db_path: str | None = None,
        agent_name: str = "runtime_host",
    ) -> None:
        self.project_root = project_root
        self.project_id = project_id or _default_project_id(project_root)
        self.logs_root = logs_root or os.path.join(project_root, "logs", "sessions")
        self.agent_name = agent_name
        self.store = SessionStore(db_path=session_db_path)
        self.state_machine = ModeStateMachine()
        self.event_log: RuntimeEventLog | None = None
        self.session: RuntimeSessionState | None = None
        self._task_id: str | None = None

    def start_session(
        self,
        *,
        user_intent: str,
        source: str = "user",
        session_id: str | None = None,
    ) -> RuntimeSessionState:
        session_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        self.session = RuntimeSessionState(
            session_id=session_id,
            project_id=self.project_id,
            last_user_intent=user_intent,
        )
        self.state_machine = ModeStateMachine(current_mode="idle")
        self.event_log = RuntimeEventLog(session_id=session_id, logs_root=self.logs_root, agent_name=self.agent_name)
        self._task_id = f"{session_id}:primary"

        session_record = self.store.create_session(session_id, self.project_id)
        if session_record is not None:
            session_record.task_count = 1
            session_record.current_active_task_id = self._task_id
            self.store.update_session(session_record)

        self.store.create_task(TaskState(
            task_id=self._task_id,
            run_id=session_id,
            status="running",
            summary=user_intent[:200],
            parent_session_id=session_id,
            project_id=self.project_id,
            started_at=self._now(),
            source=source,
        ))

        self._append("session_started", payload={"project_id": self.project_id, "source": source})
        self._append("user_message_received", payload={"source": source, "message": user_intent[:500]})
        self._persist_snapshot()
        return self.session

    def restore_session(self, session_id: str) -> RuntimeSessionState | None:
        snapshot = self.store.get_snapshot(session_id)
        if snapshot is None:
            return None
        self.session = RuntimeSessionState(
            session_id=snapshot.session_id,
            project_id=snapshot.project_id,
            current_mode=snapshot.current_mode,
            route_target=snapshot.route_target,
            execution_mode=snapshot.execution_mode,
            pending_tool_call=snapshot.pending_tool_call,
            completed_steps=list(snapshot.completed_steps),
            pending_steps=list(snapshot.pending_steps),
            modified_files=list(snapshot.modified_files),
            diff_refs=list(snapshot.diff_refs),
            diagnostic_refs=list(snapshot.diagnostic_refs),
            review_status=snapshot.review_status,
            collaboration_artifacts=dict(snapshot.collaboration_artifacts),
            event_log_position=snapshot.event_log_position or 0,
            last_user_intent=snapshot.last_user_intent,
            status=str(snapshot.metadata.get("status") or "running"),
            last_error=str(snapshot.metadata.get("last_error") or ""),
        )
        self.state_machine = ModeStateMachine(current_mode=self.session.current_mode)
        self.event_log = RuntimeEventLog(session_id=session_id, logs_root=self.logs_root, agent_name=self.agent_name)
        self._task_id = f"{session_id}:primary"
        self._append("session_restored", payload={"snapshot_version": snapshot.snapshot_version})
        self.change_mode("recovery", reason="restore_session")
        return self.session

    def apply_route(
        self,
        *,
        route_target: str | None,
        execution_mode: str,
        parallel_subtasks: list[str] | None = None,
    ) -> None:
        session = self._require_session()
        session.route_target = route_target
        session.execution_mode = execution_mode or "single_agent"
        if parallel_subtasks:
            session.set_pending_steps([f"parallel: {task}" for task in parallel_subtasks])
            self._append(
                "parallel_subtasks_detected",
                payload={"count": len(parallel_subtasks), "subtasks": list(parallel_subtasks)},
            )
        target_mode = mode_for_route(route_target, session.execution_mode)
        self.change_mode(target_mode, reason="route_applied")

    def change_mode(self, to_mode: str, *, reason: str = "", payload: dict[str, Any] | None = None) -> None:
        session = self._require_session()
        from_mode = self.state_machine.current_mode
        try:
            previous_mode, current_mode = self.state_machine.transition(to_mode)
        except IllegalModeTransition as exc:
            self._append(
                "session_failed",
                payload={"error": str(exc), "from_mode": from_mode, "to_mode": to_mode},
            )
            raise
        session.current_mode = current_mode
        body = {"from_mode": previous_mode, "to_mode": current_mode, "reason": reason}
        if payload:
            body.update(payload)
        self._append("mode_changed", payload=body)
        self._persist_snapshot()

    def begin_llm_turn(self, turn_id: int, *, selected_agent: str = "") -> None:
        session = self._require_session()
        session.turn_id = turn_id
        self._append("llm_call_started", payload={"turn_id": turn_id, "selected_agent": selected_agent})

    def complete_llm_turn(self, turn_id: int, *, selected_agent: str = "", result_summary: str = "") -> None:
        self._append(
            "llm_call_completed",
            payload={"turn_id": turn_id, "selected_agent": selected_agent, "result_summary": result_summary[:300]},
        )
        self._persist_snapshot()

    def request_tool(self, tool_name: str, *, target: str | None = None, risk_level: str = "medium") -> None:
        session = self._require_session()
        session.pending_tool_call = tool_name
        session.advance_step()
        payload = {"tool_name": tool_name, "target": target, "risk_level": risk_level}
        self._append("tool_requested", payload=payload)
        self._append("tool_allowed", payload=payload)
        self._append("tool_started", payload=payload)
        self._persist_snapshot()

    def block_tool(self, tool_name: str, *, reason: str, target: str | None = None) -> None:
        session = self._require_session()
        session.pending_tool_call = None
        self._append("tool_blocked", payload={"tool_name": tool_name, "target": target, "reason": reason})
        self._persist_snapshot()

    def complete_tool(
        self,
        tool_name: str,
        *,
        result_summary: str = "",
        modified_files: list[str] | None = None,
        diff_refs: list[str] | None = None,
        collaboration_artifacts: dict[str, Any] | None = None,
    ) -> None:
        session = self._require_session()
        session.pending_tool_call = None
        session.merge_modified_files(modified_files)
        session.merge_diff_refs(diff_refs)
        session.sync_collaboration_artifacts(collaboration_artifacts)
        if modified_files:
            self._append("diff_generated", payload={"tool_name": tool_name, "modified_files": list(modified_files)})
            self._append("diff_applied", payload={"tool_name": tool_name, "modified_files": list(modified_files)})
        self._append("tool_completed", payload={"tool_name": tool_name, "result_summary": result_summary[:300]})
        self._persist_snapshot()

    def fail_tool(self, tool_name: str, *, error: str) -> None:
        session = self._require_session()
        session.pending_tool_call = None
        session.last_error = error
        self._append("tool_failed", payload={"tool_name": tool_name, "error": error[:500]})
        self._persist_snapshot()

    def record_handoff(self, *, target_agent: str, completed: bool) -> None:
        event_type = "handoff_completed" if completed else "handoff_requested"
        self._append(event_type, payload={"target_agent": target_agent})
        self._persist_snapshot()

    def begin_diagnostic(self, *, diagnostic_type: str, target: str | None = None) -> None:
        if self.state_machine.can_transition("diagnose"):
            self.change_mode("diagnose", reason="diagnostic_started")
        self._append("diagnostic_started", payload={"diagnostic_type": diagnostic_type, "target": target})

    def complete_diagnostic(self, *, diagnostic_ref: str | None = None, summary: str = "") -> None:
        session = self._require_session()
        session.merge_diagnostic_refs([diagnostic_ref] if diagnostic_ref else [])
        self._append("diagnostic_completed", payload={"diagnostic_ref": diagnostic_ref, "summary": summary[:300]})
        self._persist_snapshot()

    def begin_review(self) -> None:
        if self.state_machine.can_transition("review"):
            self.change_mode("review", reason="review_started")
        self._append("review_started", payload={})

    def complete_review(self, *, verdict: str, summary: str = "") -> None:
        session = self._require_session()
        session.review_status = verdict
        if verdict == "needs_fix" and self.state_machine.can_transition("needs_fix"):
            self.change_mode("needs_fix", reason="review_verdict")
        self._append("review_completed", payload={"verdict": verdict, "summary": summary[:300]})
        self._persist_snapshot()

    def request_stop(self, *, reason: str) -> None:
        session = self._require_session()
        session.status = "stopped"
        self._append("stop_requested", payload={"reason": reason})
        if self.state_machine.can_transition("stopped"):
            self.change_mode("stopped", reason=reason)
        self._append("session_stopped", payload={"reason": reason})
        self._update_task(status="aborted", exit_reason=reason)
        self._persist_snapshot()

    def complete_session(self, *, summary: str = "") -> None:
        session = self._require_session()
        session.status = "completed"
        if self.state_machine.can_transition("completed"):
            self.change_mode("completed", reason="session_complete")
        self._append("session_completed", payload={"summary": summary[:500]})
        self._update_task(status="completed", exit_reason="completed", summary=summary)
        self._persist_snapshot()

    def fail_session(self, *, error: str) -> None:
        session = self._require_session()
        session.status = "error"
        session.last_error = error
        if self.state_machine.can_transition("failed"):
            self.change_mode("failed", reason="session_failed")
        self._append("session_failed", payload={"error": error[:500]})
        self._update_task(status="error", exit_reason=error[:200], summary=error)
        self._persist_snapshot()

    def sync_collaboration_store(self, store: Any | None) -> None:
        session = self._require_session()
        if store is None:
            return
        snapshot_fn = getattr(store, "snapshot", None)
        if callable(snapshot_fn):
            try:
                session.sync_collaboration_artifacts(snapshot_fn())
            except Exception:
                pass
        self._persist_snapshot()

    def _append(self, event_type: str, *, payload: dict[str, Any]) -> RuntimeEvent:
        session = self._require_session()
        if self.event_log is None:
            raise RuntimeError("runtime event log is not initialized")
        event = RuntimeEvent(
            event_type=event_type,
            session_id=session.session_id,
            turn_id=session.turn_id,
            step_id=session.step_id,
            mode=session.current_mode,
            agent=self.agent_name,
            payload=payload,
        )
        self.event_log.append(event)
        session.event_log_position = self.event_log.event_count()
        return event

    def _persist_snapshot(self) -> None:
        session = self._require_session()
        snapshot = session.to_snapshot()
        self.store.save_snapshot(snapshot)
        if self.event_log is not None:
            self.event_log.write_snapshot(snapshot.to_dict())

    def _update_task(self, *, status: str, exit_reason: str, summary: str = "") -> None:
        if not self._task_id:
            return
        task = self.store.get_task(self._task_id)
        if task is None:
            return
        task.status = status
        task.exit_reason = exit_reason
        task.completed_at = self._now()
        if summary:
            task.summary = summary[:200]
        self.store.update_task(task)
        session_record = self.store.get_session(task.parent_session_id)
        if session_record is not None:
            session_record.current_active_task_id = None
            session_record.last_completed_task_id = task.task_id
            session_record.ended_at = self._now()
            self.store.update_session(session_record)

    def _require_session(self) -> RuntimeSessionState:
        if self.session is None:
            raise RuntimeError("runtime session has not been started")
        return self.session

    @staticmethod
    def _now() -> float:
        import time
        return time.time()

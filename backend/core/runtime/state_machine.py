from __future__ import annotations

from dataclasses import dataclass


class IllegalModeTransition(ValueError):
    """Raised when a runtime mode transition is not allowed."""


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"direct_answer", "plan", "code", "diagnose", "recovery", "stopped", "failed"},
    "direct_answer": {"completed", "failed", "stopped", "review"},
    "plan": {"code", "diagnose", "review", "failed", "stopped"},
    "code": {"diagnose", "review", "completed", "failed", "stopped"},
    "diagnose": {"code", "review", "failed", "stopped", "completed"},
    "review": {"code", "completed", "needs_fix", "failed", "stopped"},
    "needs_fix": {"code", "diagnose", "failed", "stopped"},
    "recovery": {"plan", "code", "review", "completed", "failed", "stopped"},
    "stopped": {"recovery", "completed", "failed"},
    "completed": set(),
    "failed": set(),
}


def mode_for_route(route_target: str | None, execution_mode: str) -> str:
    if route_target == "chat":
        return "direct_answer"
    if execution_mode == "multi_agent":
        return "code"
    if route_target in {"code", "review", "research", "executor"}:
        return "code"
    return "plan"


@dataclass
class ModeStateMachine:
    current_mode: str = "idle"

    def can_transition(self, to_mode: str) -> bool:
        if to_mode == self.current_mode:
            return True
        return to_mode in ALLOWED_TRANSITIONS.get(self.current_mode, set())

    def transition(self, to_mode: str) -> tuple[str, str]:
        from_mode = self.current_mode
        if to_mode == from_mode:
            return from_mode, to_mode
        if not self.can_transition(to_mode):
            raise IllegalModeTransition(f"illegal runtime mode transition: {from_mode} -> {to_mode}")
        self.current_mode = to_mode
        return from_mode, to_mode

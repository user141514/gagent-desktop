from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

RuntimeEventType = Literal[
    "session_started",
    "user_message_received",
    "mode_changed",
    "llm_call_started",
    "llm_call_completed",
    "tool_requested",
    "tool_allowed",
    "tool_blocked",
    "tool_started",
    "tool_completed",
    "tool_failed",
    "file_read",
    "file_write_requested",
    "diff_generated",
    "diff_applied",
    "diagnostic_started",
    "diagnostic_completed",
    "review_started",
    "review_completed",
    "stop_requested",
    "session_stopped",
    "session_restored",
    "session_completed",
    "session_failed",
    "handoff_requested",
    "handoff_completed",
    "parallel_subtasks_detected",
    "snapshot_saved",
]


def timestamp_to_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().isoformat()


@dataclass
class RuntimeEvent:
    """Canonical runtime event for execution tracing and recovery."""

    event_type: str
    session_id: str
    turn_id: int = 0
    step_id: int = 0
    mode: str = "idle"
    agent: str = "runtime_host"
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    event_id: str = ""

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if not self.event_id:
            suffix = uuid.uuid4().hex[:12]
            self.event_id = f"evt_{suffix}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "timestamp_iso": timestamp_to_iso(self.timestamp),
            "event_type": self.event_type,
            "mode": self.mode,
            "agent": self.agent,
            "payload": dict(self.payload),
        }

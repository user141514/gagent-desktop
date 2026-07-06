"""Agent output event types — replaces the implicit display-queue dict protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Event kind constants (str-based, Python 3.7 compatible)
EVENT_KINDS = frozenset({
    "chunk",        # incremental streaming text (was {"next": ...})
    "done",         # final response (was {"done": ...})
    "status",       # non-text backend status/progress event
    "turn_start",   # new LLM turn began
    "turn_end",     # LLM turn completed
    "turn_delta",   # delta within a turn (paired with chunk)
    "thinking_block",  # LLM reasoning/thinking content block
    "frontier_state",  # expandable research/audit state snapshot
    "stopped",      # user aborted
    "error",        # backend exception
})


# Mapping from legacy dict keys to str
_LEGACY_KEY_MAP: dict[str, str] = {
    "next": "chunk",
    "done": "done",
}

_LEGACY_EVENT_MAP: dict[str, str] = {
    "turn_start": "turn_start",
    "turn_end": "turn_end",
    "turn_delta": "turn_delta",
    "final": "done",
    "stopped": "stopped",
    "error": "error",
}


def _coerce_int(*values: Any) -> int:
    for value in values:
        try:
            if value is None or value == "":
                continue
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


@dataclass
class AgentOutputEvent:
    """Canonical output unit emitted by an agent backend.

    Replaces the ad-hoc dict protocol where frontends checked for
    ``"next" in item``, ``"done" in item``, or ``item.get("event")``.
    """

    kind: str  # one of EVENT_KINDS
    text: str = ""
    source: str = "user"
    turn: int = 0
    task_id: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_legacy_dict(cls, item: dict[str, Any]) -> AgentOutputEvent:
        """Convert a legacy display-queue dict to a typed event.

        Handles both:
        - Key-based items: {"next": ..., "turn": ...}, {"done": ..., "turn": ...}
        - Event-based items: {"event": "turn_start", ...}, {"event": "stopped", ...}
        """
        kind: str = "chunk"  # one of EVENT_KINDS
        text = ""
        error = ""
        metadata: dict[str, Any] = {}

        # Check event key first
        event_label = item.get("event", "")
        item_type = item.get("type", "")
        if item_type == "status":
            event_type = item.get("event_type", "")
            if event_type == "classic_turn_started":
                kind = "turn_start"
            elif event_type in ("thinking_delta", "thinking_blocks"):
                kind = "thinking_block"
                text = str(item.get("message", ""))
            else:
                kind = "status"
                text = str(item.get("message", ""))
        elif event_label in _LEGACY_EVENT_MAP:
            kind = _LEGACY_EVENT_MAP[event_label]
            if kind == "stopped":
                text = item.get("next", "")
            elif kind == "done":
                text = item.get("done", "")
            elif kind == "error":
                error = item.get("error", "")
                text = item.get("done", item.get("next", ""))
            elif kind == "turn_delta":
                text = item.get("next", "")
        elif "done" in item:
            kind = "done"
            text = item.get("done", "")
        elif "next" in item:
            kind = "chunk"
            text = item.get("next", "")
        else:
            # Unknown shape — treat as chunk with empty text
            kind = "chunk"

        # Populate metadata from extra keys
        for key in ("final_answer_ready", "final_answer_text", "shortcut_type",
                     "skip_planner_followup", "shortcut_reason", "shortcut_confidence",
                     "tool_error", "scope", "agent_name", "message", "type",
                     "event_type", "classic_turn", "max_turns", "execution_state",
                     "audit_context", "research_workflow_score", "frontier_state"):
            if key in item:
                metadata[key] = item[key]

        return cls(
            kind=kind,
            text=str(text),
            source=str(item.get("source", "user")),
            turn=_coerce_int(
                item.get("turn"),
                item.get("classic_turn"),
                item.get("current_turn"),
                item.get("llm_turn"),
            ),
            task_id=str(item.get("task_id", "")),
            error=str(error),
            metadata=metadata,
        )

    def is_terminal(self) -> bool:
        """True if this event signals the end of a task."""
        return self.kind in ("done", "stopped", "error")

    def to_legacy_dict(self) -> dict[str, Any]:
        """Convert back to legacy dict format for backward compatibility."""
        item: dict[str, Any] = {
            "source": self.source,
            "turn": self.turn,
            "task_id": self.task_id,
        }
        if self.kind == "chunk":
            item["next"] = self.text
        elif self.kind == "done":
            item["done"] = self.text
        elif self.kind == "stopped":
            item["event"] = "stopped"
            item["next"] = self.text
        elif self.kind == "error":
            item["event"] = "error"
            item["error"] = self.error
        elif self.kind in ("turn_start", "turn_end", "turn_delta"):
            item["event"] = self.kind
            if self.text:
                item["next"] = self.text
        elif self.kind == "frontier_state":
            item["event"] = "frontier_state"
        item.update(self.metadata)
        return item

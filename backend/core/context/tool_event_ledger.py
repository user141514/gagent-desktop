"""
Tool Event Ledger — executed fact evidence for the canonical context pipeline.

Design rules:
  4. Tool Event Ledger is the ONLY evidence of executed facts.
  5. Assistant final text is NOT execution evidence.
  6. Pending proposals must be separated from executed changes.

The ledger is a lightweight in-memory append-only log. It does NOT:
  - Write to L1/L2 files
  - Write to SQLite
  - Write to inbox
  - Modify the agent loop behavior

Gated by GA_TOOL_EVENT_LEDGER env var (default: off).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

LEDGER_ENV_VAR = "GA_TOOL_EVENT_LEDGER"


def tool_event_ledger_enabled() -> bool:
    return os.environ.get(LEDGER_ENV_VAR, "").strip() == "1"


@dataclass
class ToolEvent:
    """A single tool invocation record — the atomic unit of executed fact."""

    tool_name: str
    args_summary: str          # compact representation of arguments
    result_summary: str = ""   # compact representation of result
    status: str = "pending"    # "pending" | "success" | "error" | "interrupted"
    target_path: str | None = None
    turn: int = 0
    index: int = 0
    timestamp: float = 0.0
    result_chars: int = 0
    error_like: bool = False

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def mark_completed(self, result_summary: str, status: str = "success",
                       result_chars: int = 0, error_like: bool = False) -> None:
        self.result_summary = result_summary[:300]
        self.status = status
        self.result_chars = result_chars
        self.error_like = error_like

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "args_summary": self.args_summary[:200],
            "result_summary": self.result_summary[:300],
            "status": self.status,
            "target_path": self.target_path,
            "turn": self.turn,
            "index": self.index,
            "timestamp": self.timestamp,
            "result_chars": self.result_chars,
            "error_like": self.error_like,
        }

    def one_line(self) -> str:
        """Compact one-line summary for ledger display."""
        status_mark = {"success": "+", "error": "!", "interrupted": "~", "pending": "?"}.get(self.status, "?")
        target = f" → {self.target_path}" if self.target_path else ""
        result = f": {self.result_summary[:80]}" if self.result_summary else ""
        return f"[{status_mark}] {self.tool_name}({self.args_summary[:80]}){target}{result}"


class ToolEventLedger:
    """In-memory append-only ledger of tool execution events.

    Usage:
        ledger = ToolEventLedger()
        event_id = ledger.start_call("file_read", {"path": "test.txt"}, turn=1)
        ledger.complete_call(event_id, result="file content...", status="success")
        summary = ledger.recent_summary()
    """

    def __init__(self, max_events: int = 50):
        self._events: list[ToolEvent] = []
        self._max_events = max_events
        self._pending: dict[str, ToolEvent] = {}

    def start_call(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        target_path: str | None = None,
        turn: int = 0,
        index: int = 0,
    ) -> str:
        """Record a tool call before execution. Returns event_id."""
        if not tool_event_ledger_enabled():
            return ""

        args_summary = _summarize_args(args)
        event = ToolEvent(
            tool_name=tool_name,
            args_summary=args_summary,
            target_path=target_path,
            turn=turn,
            index=index,
        )

        event_id = f"{tool_name}_{turn}_{index}_{time.time()}"
        self._pending[event_id] = event
        return event_id

    def complete_call(
        self,
        event_id: str,
        result: str = "",
        status: str = "success",
        result_chars: int = 0,
        error_like: bool = False,
    ) -> None:
        """Mark a tool call as completed with its result."""
        if not event_id:
            return

        event = self._pending.pop(event_id, None)
        if event is None:
            return

        event.mark_completed(
            result_summary=_summarize_result(result),
            status=status,
            result_chars=result_chars,
            error_like=error_like,
        )
        self._events.append(event)

        # Trim old events
        while len(self._events) > self._max_events:
            self._events.pop(0)

    def recent_events(self, n: int = 20) -> list[ToolEvent]:
        """Return the N most recent tool events."""
        return self._events[-n:]

    def recent_summary(self, n: int = 10) -> str:
        """Compact text summary of recent tool events for context injection."""
        events = self.recent_events(n)
        if not events:
            return ""

        lines = ["### [TOOL EVENT LEDGER — executed facts]"]
        for e in events:
            lines.append(e.one_line())
        lines.append(f"[/TOOL EVENT LEDGER — {len(events)} events]")
        return "\n".join(lines)

    def events_by_status(self, status: str) -> list[ToolEvent]:
        """Filter events by status."""
        return [e for e in self._events if e.status == status]

    def error_events(self) -> list[ToolEvent]:
        """Return all error events."""
        return self.events_by_status("error")

    def pending_count(self) -> int:
        """Number of uncompleted tool calls."""
        return len(self._pending)

    def clear(self) -> None:
        """Reset the ledger."""
        self._events.clear()
        self._pending.clear()


# ═══ Helpers ════════════════════════════════════════════════════════════════

def _summarize_args(args: dict[str, Any] | None) -> str:
    """Compact representation of tool arguments."""
    if not args:
        return ""
    safe = {k: v for k, v in args.items() if k != "_index"}
    # For file operations, show the path
    if "path" in safe:
        path = str(safe["path"])
        if len(path) > 60:
            path = "..." + path[-57:]
        extra = {k: v for k, v in safe.items() if k != "path"}
        if extra:
            return f"path={path}, {_dict_str(extra, 40)}"
        return f"path={path}"
    return _dict_str(safe, 100)


def _summarize_result(result: str) -> str:
    """Compact representation of tool result."""
    if not result:
        return ""
    text = str(result).replace("\n", " ").replace("\r", " ").strip()
    if len(text) > 200:
        return text[:197] + "..."
    return text


def _dict_str(d: dict, max_len: int) -> str:
    """Compact dict to string, truncating at max_len."""
    try:
        import json
        s = json.dumps(d, ensure_ascii=False, default=str)
    except Exception:
        s = str(d)
    if len(s) > max_len:
        return s[:max_len - 3] + "..."
    return s

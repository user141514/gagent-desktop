"""Bridge: agent lifecycle -> RuntimeHost session recording.

Belongs to ``core/runtime/`` — uses RuntimeHost internals.
Depends on ``core.protocol`` (the pure-data contract layer).

Dependency direction::

    core.protocol          core.runtime.host
         ▲                      ▲
         │                      │
    core.runtime.protocol_bridge ── wires the two together

Callers (agent loop) pass primitive values — the mapper internally
translates to RuntimeHost method calls and RuntimeEvent emissions.
No ``AgentOutputEvent`` construction required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.runtime.host import RuntimeHost


class RuntimeEventMapper:
    """Translates agent lifecycle events into RuntimeHost session recording.

    Every method is a no-op when ``host=None`` (CLI without persistence).
    Callers pass primitive values (turn number, tool name, text) —
    the mapper handles the RuntimeHost call translation internally.
    """

    def __init__(self, host: RuntimeHost | None = None) -> None:
        self._host: RuntimeHost | None = host

    @property
    def active(self) -> bool:
        return self._host is not None

    # ── session lifecycle ───────────────────────────────────────────────

    def on_session_start(self, user_intent: str, source: str = "user") -> None:
        if self._host is None:
            return
        self._host.start_session(user_intent=user_intent, source=source)

    def on_user_message(self, query: str, source: str = "user") -> None:
        if self._host is None:
            return
        self._host._append(
            "user_message_received",
            payload={"query": query[:500], "source": source},
        )

    # ── turn lifecycle ──────────────────────────────────────────────────

    def on_turn_start(self, turn: int, source: str = "", task_id: str = "") -> None:
        if self._host is None:
            return
        state = self._host._require_session()
        state.advance_turn()
        self._host._append(
            "llm_call_started",
            payload={"turn": turn, "source": source, "task_id": task_id},
        )

    def on_turn_end(self, turn: int, source: str = "", task_id: str = "") -> None:
        if self._host is None:
            return
        self._host._append(
            "llm_call_completed",
            payload={"turn": turn, "source": source, "task_id": task_id},
        )

    # ── tool lifecycle ──────────────────────────────────────────────────

    def on_tool_requested(self, tool_name: str, args: dict | None = None) -> None:
        if self._host is None:
            return
        target = None
        if args:
            target = args.get("path") or args.get("target_path") or args.get("url")
        self._host.request_tool(tool_name, target=target)

    def on_tool_completed(self, tool_name: str, result_summary: str = "") -> None:
        if self._host is None:
            return
        self._host.complete_tool(tool_name, result_summary=result_summary or "ok")

    # ── terminal events ─────────────────────────────────────────────────

    def on_error(self, error_message: str) -> None:
        if self._host is None:
            return
        self._host.fail_session(error=error_message)

    def on_done(self, summary: str = "") -> None:
        if self._host is None:
            return
        self._host.complete_session(
            summary=summary[:200] if summary else "(empty response)"
        )

    def on_stop_requested(self) -> None:
        if self._host is None:
            return
        self._host.request_stop(reason="user_requested")

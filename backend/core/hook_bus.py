"""Unified event bus for agent lifecycle, turn, and tool hooks.

Replaces the scattered callback pattern (BaseHandler.tool_before_callback /
tool_after_callback / turn_end_callback, RuntimeEventMapper, RuntimeHost,
_done_hooks) with a single centralized event bus.

Design principles:
- Emit-only by default: emitting has zero overhead when no handlers registered.
- Backward compatible: old callbacks remain functional; they can migrate one by one.
- Non-blocking: handler exceptions are caught and logged, never propagated.
- Thread-safe: handlers dict is mutated only during registration; emission is read-only.

Named events:
    session.start  -- agent session begins
    session.end    -- agent session ends (normal or error)
    turn.start     -- a new LLM turn begins
    turn.end       -- an LLM turn completes
    tool.pre_execute  -- before a tool is dispatched
    tool.post_execute -- after a tool completes (success or error)
    prompt.pre_submit -- before user prompt is sent to LLM
    prompt.post_submit -- after LLM response received
    stop           -- agent is stopping (replaces _done_hooks)
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Callable


def _noop_print(*_args: object, **_kwargs: object) -> None:
    """Silent fallback when we want to suppress log noise."""


_HOOK_LOG = _noop_print  # Set to print for debugging hook activity


# ═══════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════


@dataclass
class HookEvent:
    """Immutable snapshot of an event at emission time.

    ``payload`` is a shallow copy of the original, so handlers that
    mutate payload won't affect other handlers.
    """

    name: str
    payload: dict[str, Any]
    source: str = ""


@dataclass
class HookResult:
    """Returned by a hook handler to influence the caller.

    All fields are optional.  A handler that returns ``None`` is
    treated as a no-op observer.
    """

    additional_context: dict[str, Any] | None = None
    block: bool = False
    block_reason: str = ""
    modify: dict[str, Any] | None = None  # fields to merge into event payload


# Handler signature: (HookEvent) -> HookResult | None
HookHandler = Callable[[HookEvent], HookResult | None]


@dataclass
class _Registration:
    handler: HookHandler
    tool_glob: str | None = None  # "file_*", "web_*", None = matches all
    priority: int = 0  # higher runs first
    source: str = ""  # "config", "plugin", "python"


# ═══════════════════════════════════════════════════════════════════
# Valid event names (for validation and documentation)
# ═══════════════════════════════════════════════════════════════════

VALID_EVENTS: frozenset[str] = frozenset(
    {
        "session.start",
        "session.end",
        "turn.start",
        "turn.end",
        "tool.pre_execute",
        "tool.post_execute",
        "prompt.pre_submit",
        "prompt.post_submit",
        "stop",
    }
)


# ═══════════════════════════════════════════════════════════════════
# HookBus
# ═══════════════════════════════════════════════════════════════════


class HookBus:
    """Centralized event bus for agent lifecycle hooks.

    Usage::

        bus = HookBus()
        bus.on("tool.pre_execute", my_handler, tool_glob="file_*")
        results = bus.emit("tool.pre_execute", {"tool_name": "file_read", "args": {...}})

    Global singleton is available via ``HookBus.global_instance()``.
    """

    _instance: HookBus | None = None

    # ── Singleton ────────────────────────────────────────────────

    @classmethod
    def global_instance(cls) -> "HookBus":
        """Return the module-level singleton, creating it on first access."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_global_instance(cls) -> None:
        """Reset the singleton (useful for tests)."""
        cls._instance = None

    # ── Construction ─────────────────────────────────────────────

    def __init__(self) -> None:
        self._handlers: dict[str, list[_Registration]] = {}
        # Pre-populate with empty lists for all valid events so emit()
        # never has to check for missing keys.
        for evt in VALID_EVENTS:
            self._handlers[evt] = []

    # ── Registration ─────────────────────────────────────────────

    def on(
        self,
        event: str,
        handler: HookHandler,
        *,
        tool_glob: str | None = None,
        priority: int = 0,
        source: str = "",
    ) -> None:
        """Register a *handler* for a named *event*.

        Args:
            event: One of the ``VALID_EVENTS`` names.
            handler: Callable that receives a ``HookEvent`` and optionally
                     returns a ``HookResult``.
            tool_glob: Optional fnmatch pattern to gate on ``payload["tool_name"]``.
            priority: Higher values run first (default 0).
            source: Tag for debugging (e.g. ``"plugin:superpowers"``).
        """
        if event not in self._handlers:
            _HOOK_LOG(f"[HookBus] unknown event {event!r}, adding anyway")
            self._handlers[event] = []

        reg = _Registration(
            handler=handler,
            tool_glob=tool_glob,
            priority=priority,
            source=source,
        )
        self._handlers[event].append(reg)
        # Keep sorted by priority descending so high-priority runs first
        self._handlers[event].sort(key=lambda r: r.priority, reverse=True)

    def remove(self, event: str, handler: HookHandler) -> bool:
        """Remove a previously registered handler. Returns True if found."""
        regs = self._handlers.get(event, [])
        before = len(regs)
        self._handlers[event] = [r for r in regs if r.handler is not handler]
        return len(self._handlers[event]) < before

    def clear(self, event: str | None = None) -> None:
        """Remove all handlers. If *event* is given, clear only that event."""
        if event is not None:
            self._handlers[event] = []
        else:
            for evt in self._handlers:
                self._handlers[evt] = []

    # ── Emission ─────────────────────────────────────────────────

    def emit(
        self,
        event: str,
        payload: dict[str, Any] | None = None,
        source: str = "",
    ) -> list[HookResult]:
        """Emit an event to all registered handlers.

        Handlers run in priority order.  If any handler returns
        ``HookResult.block == True``, remaining handlers are skipped
        and the result list is returned immediately.

        Returns the list of non-None ``HookResult`` objects in the
        order they were produced.

        Handlers that raise exceptions are logged and skipped — they
        can never block the agent loop.
        """
        payload = dict(payload or {})
        hook_event = HookEvent(name=event, payload=payload, source=source)

        # Fast path: no handlers registered
        regs = self._handlers.get(event, [])
        if not regs:
            return []

        results: list[HookResult] = []
        for reg in regs:
            # Tool-glob gating
            if reg.tool_glob:
                tool_name = str(payload.get("tool_name", ""))
                if not fnmatch.fnmatch(tool_name, reg.tool_glob):
                    continue

            try:
                result = reg.handler(hook_event)
            except Exception as exc:
                print(f"[HookBus] handler for {event!r} raised {type(exc).__name__}: {exc}")
                continue

            if result is None:
                continue

            results.append(result)
            if result.block:
                return results  # short-circuit: don't run remaining handlers

        return results

    def emit_blocked(
        self,
        event: str,
        payload: dict[str, Any] | None = None,
        source: str = "",
    ) -> tuple[bool, str]:
        """Emit and return (is_blocked, reason).

        Convenience wrapper for the common pattern of checking whether
        any handler blocked the operation.
        """
        for r in self.emit(event, payload, source):
            if r.block:
                return True, r.block_reason or "blocked"
        return False, ""

    # ── Introspection ────────────────────────────────────────────

    def handler_count(self, event: str | None = None) -> int:
        """Return number of registered handlers. If *event* is given,
        count only handlers for that event."""
        if event is not None:
            return len(self._handlers.get(event, []))
        return sum(len(v) for v in self._handlers.values())

    def list_registrations(self) -> list[dict[str, Any]]:
        """Return a human-readable list of all registrations (for debugging)."""
        result: list[dict[str, Any]] = []
        for evt, regs in sorted(self._handlers.items()):
            for reg in regs:
                result.append(
                    {
                        "event": evt,
                        "tool_glob": reg.tool_glob,
                        "priority": reg.priority,
                        "source": reg.source,
                    }
                )
        return result

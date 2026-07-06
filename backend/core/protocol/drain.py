"""Agent output drainer — shared queue-draining logic for all frontends.

Replaces the 5+ distinct queue-draining implementations spread across
stapp.py, stapp_mobile.py, stapp2.py, qtapp.py, chatapp_common.py, etc.
"""

from __future__ import annotations

import queue
from typing import Iterator, Optional

from .channel import AgentOutputChannel, QueueOutputChannel
from .events import AgentOutputEvent


class AgentOutputDrainer:
    """Shared queue-draining utility. All frontends use this.

    Replaces per-frontend patterns like::

        # stapp.py / stapp_mobile.py
        for _ in range(20):
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
            if "next" in item:
                st.session_state.partial_response = item["next"]
            if "done" in item:
                ...

        # qtapp.py
        while True:
            try:
                item = self._display_queue.get_nowait()
            except _queue.Empty:
                break
            ...

    With::

        drainer = AgentOutputDrainer(channel)
        text = drainer.collect()       # drain all available items
        if drainer.is_done:
            finalize(drainer.full_text)
    """

    def __init__(self, channel: AgentOutputChannel, *,
                 task_id: str = "",
                 stop_requested: bool = False) -> None:
        self._channel = channel
        self._full_text = ""
        self._current_turn = 0
        self._is_done = False
        self._is_stopped = False
        self._is_error = False
        self._error_msg = ""
        self._events: list[AgentOutputEvent] = []
        self._metadata: dict = {}
        self._task_id = task_id
        self._stop_requested = stop_requested

    # ── mutable filter controls (updated by caller between collect() calls) ─

    @property
    def stop_requested(self) -> bool:
        """When True, ``collect()`` skips non-terminal events (chunk/turn_*)."""
        return self._stop_requested

    @stop_requested.setter
    def stop_requested(self, value: bool) -> None:
        self._stop_requested = value

    @property
    def task_id(self) -> str:
        """Task ID filter. When set, events with a different task_id are skipped."""
        return self._task_id

    @task_id.setter
    def task_id(self, value: str) -> None:
        self._task_id = value

    # ── read-only state ──────────────────────────────────────────────────

    @property
    def full_text(self) -> str:
        """Accumulated response text so far."""
        return self._full_text

    @property
    def current_turn(self) -> int:
        """Current LLM turn number."""
        return self._current_turn

    @property
    def is_done(self) -> bool:
        """True if a terminal 'done' event has been received."""
        return self._is_done

    @property
    def is_stopped(self) -> bool:
        """True if the task was aborted."""
        return self._is_stopped

    @property
    def is_error(self) -> bool:
        """True if the task errored."""
        return self._is_error

    @property
    def error_msg(self) -> str:
        """Error message if is_error."""
        return self._error_msg

    @property
    def metadata(self) -> dict:
        """Metadata from the done event (shortcut info, etc.)."""
        return dict(self._metadata)

    @property
    def is_terminal(self) -> bool:
        """True if the task has reached any terminal state."""
        return self._is_done or self._is_stopped or self._is_error

    @property
    def recent_events(self) -> list[AgentOutputEvent]:
        """Events collected in the last drain cycle (cleared each collect())."""
        return list(self._events)

    # ── drain methods ────────────────────────────────────────────────────

    def _accept(self, event: AgentOutputEvent) -> bool:
        """True if this event should be processed under current filters."""
        if self._task_id and event.task_id and event.task_id != self._task_id:
            return False
        if self._stop_requested and not event.is_terminal():
            return False
        return True

    def collect(self, max_items: int = 20) -> str | None:
        """Non-blocking drain: read up to *max_items* from the channel.

        Respects ``stop_requested`` (skip non-terminal) and ``task_id`` filters.
        Returns the latest chunk text, or None if nothing new.
        Call this in a poll loop (e.g., every 0.2s with st.rerun()).
        """
        self._events.clear()
        latest = None
        for _ in range(max_items):
            event = self._channel.get_nowait()
            if event is None:
                break
            self._events.append(event)
            if not self._accept(event):
                continue
            self._apply(event)
            if event.kind == "chunk":
                latest = event.text
            if event.is_terminal():
                break
        return latest

    def drain_all(self) -> list[AgentOutputEvent]:
        """Blocking drain: read all remaining events. Respects filters."""
        self._events.clear()
        results: list[AgentOutputEvent] = []
        while True:
            event = self._channel.get(timeout=0.1)
            if event is None:
                break
            self._events.append(event)
            if not self._accept(event):
                continue
            results.append(event)
            self._apply(event)
            if event.is_terminal():
                break
        return results

    def wait_for_done(self, timeout: float | None = None) -> AgentOutputEvent | None:
        """Block until a terminal event arrives. Returns the terminal event or None."""
        while True:
            event = self._channel.get(timeout=0.5 if timeout is None else min(timeout, 0.5))
            if event is None:
                if timeout is not None:
                    timeout -= 0.5
                    if timeout <= 0:
                        return None
                    continue
                continue
            self._apply(event)
            if event.is_terminal():
                return event
        return None

    # ── internal ─────────────────────────────────────────────────────────

    def _apply(self, event: AgentOutputEvent) -> None:
        if event.kind == "chunk":
            self._full_text = event.text
        elif event.kind == "done":
            self._full_text = event.text
            self._is_done = True
            self._metadata = dict(event.metadata)
        elif event.kind == "stopped":
            self._full_text = event.text
            self._is_stopped = True
        elif event.kind == "error":
            self._error_msg = event.error
            self._is_error = True
            if event.text:
                self._full_text = event.text
        if event.turn > 0:
            self._current_turn = max(self._current_turn, event.turn)

    # ── legacy adapter ───────────────────────────────────────────────────

    @classmethod
    def from_legacy_queue(cls, legacy_q: queue.Queue) -> AgentOutputDrainer:
        """Create a drainer from a legacy raw-dict queue.

        Uses the QueueOutputChannel bridge for backward compatibility.
        Frontends can adopt the drainer without first switching to
        AgentOutputChannel.submit().
        """
        channel = QueueOutputChannel.from_legacy_queue(legacy_q)
        return cls(channel)

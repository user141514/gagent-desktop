"""Agent output channel — abstract pipe between agent and frontend."""

from __future__ import annotations

import queue
from abc import ABC, abstractmethod
from typing import Iterator

from .events import AgentOutputEvent

_SENTINEL = object()  # placed in queue on close() to unblock get()


class AgentOutputChannel(ABC):
    """Abstract output channel consumed by frontends.

    Replaces raw ``queue.Queue`` as the return value of agent task submission.
    Frontends use this to receive streaming output without knowing whether
    the backend is local (queue.Queue) or remote (WebSocket, etc.).
    """

    @abstractmethod
    def put(self, event: AgentOutputEvent) -> None:
        """Push an event into the channel (called by agent backend)."""
        ...

    @abstractmethod
    def get(self, timeout: float | None = None) -> AgentOutputEvent | None:
        """Block until an event is available, or return None on timeout/close."""
        ...

    @abstractmethod
    def get_nowait(self) -> AgentOutputEvent | None:
        """Return an event if available, or None immediately."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Signal that no more events will be produced."""
        ...

    @property
    @abstractmethod
    def closed(self) -> bool:
        """Whether the channel has been closed."""
        ...


class QueueOutputChannel(AgentOutputChannel):
    """Concrete channel backed by a ``queue.Queue``.

    Used for local (same-process) agent backends.
    Wraps legacy raw-dict queue with typed event conversion.

    Uses a sentinel object to unblock ``get()`` when ``close()`` is called,
    so consumers never hang indefinitely.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._closed = False
        self._source_legacy_queue: queue.Queue | None = None

    @property
    def legacy_queue(self) -> queue.Queue:
        """The raw ``queue.Queue[dict]`` backing this channel, if any.

        Returns the original queue that the agent backend writes raw dicts
        (``{"next": ..., "done": ...}``) into.  Only set when this channel
        was created via ``from_legacy_queue()``.

        Raises:
            RuntimeError: If this channel has no legacy queue (e.g. created
                          directly without ``from_legacy_queue()``).
        """
        if self._source_legacy_queue is None:
            raise RuntimeError(
                "QueueOutputChannel has no legacy queue. "
                "It was not created via from_legacy_queue()."
            )
        return self._source_legacy_queue

    def put(self, event: AgentOutputEvent) -> None:
        if not self._closed:
            self._queue.put(event)

    def get(self, timeout: float | None = None) -> AgentOutputEvent | None:
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is _SENTINEL:
            return None
        if isinstance(item, AgentOutputEvent):
            return item
        return None

    def get_nowait(self) -> AgentOutputEvent | None:
        try:
            item = self._queue.get_nowait()
        except queue.Empty:
            return None
        if item is _SENTINEL:
            return None
        if isinstance(item, AgentOutputEvent):
            return item
        return None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put(_SENTINEL)

    @property
    def closed(self) -> bool:
        return self._closed

    def qsize(self) -> int:
        """Approximate number of events in the queue (excluding sentinel)."""
        return self._queue.qsize()

    @classmethod
    def from_legacy_queue(cls, legacy_q: queue.Queue) -> QueueOutputChannel:
        """Wrap a legacy raw-dict queue for backward compatibility.

        Reads raw dicts from the legacy queue and converts them to
        ``AgentOutputEvent`` on the fly via a background bridge thread.
        The returned channel provides the new typed interface while the
        producer still uses raw dicts.

        The bridge runs until a terminal event (done/stopped/error) is seen
        or the channel is closed.
        """
        channel = cls()
        channel._source_legacy_queue = legacy_q  # for put_task() backward compat

        def _bridge() -> None:
            while not channel._closed:
                try:
                    item = legacy_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is None:
                    break
                try:
                    event = AgentOutputEvent.from_legacy_dict(item)
                except Exception:
                    continue
                channel._queue.put(event)
                if event.is_terminal():
                    break
            channel.close()

        import threading
        t = threading.Thread(target=_bridge, daemon=True)
        t.start()
        return channel

    def __len__(self) -> int:
        return self.qsize()

    def __iter__(self) -> Iterator[AgentOutputEvent]:
        while True:
            event = self.get()
            if event is None:
                break
            yield event
            if event.is_terminal():
                break

"""Agent backend abstract interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .channel import AgentOutputChannel
from .input import AgentInput


class AgentBackend(ABC):
    """Abstract interface that every agent backend must implement.

    Frontends depend on this ABC instead of importing concrete agent classes.
    This enables:
    - Swapping between classic and multi-agent backends transparently
    - Testing frontends with mock backends
    - Remote backends (the channel can be a WebSocket instead of a local queue)
    """

    @abstractmethod
    def submit(self, task: AgentInput) -> AgentOutputChannel:
        """Submit a task and return a channel for streaming output.

        Replaces ``put_task(query, source, images, run_id) -> queue.Queue``.
        """
        ...

    @abstractmethod
    def abort(self) -> None:
        """Request cancellation of the currently running task."""
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether a task is currently being processed."""
        ...

    @abstractmethod
    def get_llm_name(self) -> str:
        """Human-readable name of the active LLM backend."""
        ...

    @abstractmethod
    def get_key_labels(self) -> list[str]:
        """Labels for available API keys (for multi-key switching UI)."""
        ...

    @abstractmethod
    def switch_to_key(self, index: int) -> str:
        """Switch to a different API key by index. Returns the new key name."""
        ...

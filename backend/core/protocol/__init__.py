"""Agent Protocol: shared contract layer between agent backends and frontends.

This package defines the formal I/O protocol that all agent backends implement
and all frontends consume. It has zero dependencies on concrete agent or UI code.

Core types:
- AgentInput: structured task submission
- AgentOutputEvent: typed output event (replaces raw dict queue items)
- AgentOutputChannel: abstract output pipe (replaces raw queue.Queue)
- AgentBackend: ABC that every agent must implement
"""

from .events import AgentOutputEvent
from .input import AgentInput
from .channel import AgentOutputChannel, QueueOutputChannel
from .agent import AgentBackend

__all__ = [
    "AgentOutputEvent",
    "AgentInput",
    "AgentOutputChannel",
    "QueueOutputChannel",
    "AgentBackend",
]

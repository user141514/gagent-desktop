"""
Runtime identity — capture the running agent process metadata.

Generates a stable session_id for the process lifetime.
Returns RuntimeIdentity or None when disabled.
"""

import os
import socket
import time
import uuid
from dataclasses import dataclass, field

from . import _context_enabled

# Module-level singleton: session_id is stable for process lifetime
_SESSION_ID: str | None = None


def _get_session_id() -> str:
    """Return a stable session_id for this process. Generated once."""
    global _SESSION_ID
    if _SESSION_ID is None:
        _SESSION_ID = "sess_" + uuid.uuid4().hex[:12]
    return _SESSION_ID


@dataclass
class RuntimeIdentity:
    """Identity of the running agent process / session."""

    session_id: str
    process_id: int
    agent_backend: str
    hostname: str
    started_at: float
    env_summary: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        # Truncate env values to 80 chars
        truncated = {}
        for k, v in self.env_summary.items():
            truncated[k] = v[:80] if len(v) > 80 else v
        self.env_summary = truncated


def detect_runtime(agent_backend: str = "") -> RuntimeIdentity | None:
    """Capture the current runtime identity.

    Args:
        agent_backend: "genericagent" or "openai-agents"

    Returns None when GA_CONTEXT_RUNTIME_ENABLED != '1'.
    """
    if not _context_enabled():
        return None

    # Collect only GA_CONTEXT_* env vars
    env_summary: dict[str, str] = {}
    for key, value in sorted(os.environ.items()):
        if key.startswith("GA_CONTEXT_"):
            env_summary[key] = value

    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"

    return RuntimeIdentity(
        session_id=_get_session_id(),
        process_id=os.getpid(),
        agent_backend=agent_backend or os.environ.get("GA_AGENT_BACKEND", "genericagent"),
        hostname=hostname,
        started_at=time.time(),
        env_summary=env_summary,
    )

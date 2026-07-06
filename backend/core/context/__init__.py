"""
Context Runtime — workspace, project, and runtime identity for agent context packets.

All modules are gated by GA_CONTEXT_RUNTIME_ENABLED env var.
Default disabled. Set GA_CONTEXT_RUNTIME_ENABLED=1 to enable (preview mode)
or GA_CONTEXT_RUNTIME_MODE=inject to inject into agent context.
"""

import os


def _context_enabled() -> bool:
    """Master kill-switch. Checked by every module entry point.

    Default disabled. Set GA_CONTEXT_RUNTIME_ENABLED=1 to enable.
    """
    return os.environ.get("GA_CONTEXT_RUNTIME_ENABLED", "0") == "1"


def _context_mode() -> str:
    """Returns 'off', 'preview', or 'inject'."""
    return os.environ.get("GA_CONTEXT_RUNTIME_MODE", "preview")


from .workspace_probe import WorkspaceProbe, WorkspaceSnapshot
from .project_identity import ProjectIdentity, detect_project
from .runtime_identity import RuntimeIdentity, detect_runtime
from .recent_turns import (
    build_recent_conversation_block,
    build_clarification_request,
    is_ambiguous_followup,
    recent_turns_enabled,
)

__all__ = [
    "_context_enabled",
    "_context_mode",
    "WorkspaceProbe",
    "WorkspaceSnapshot",
    "ProjectIdentity",
    "detect_project",
    "RuntimeIdentity",
    "detect_runtime",
    "build_recent_conversation_block",
    "build_clarification_request",
    "is_ambiguous_followup",
    "recent_turns_enabled",
]

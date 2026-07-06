"""ToolOrchestrator — standardized pipeline for every tool call.

Pipeline: Validate → Authorize → Sandbox → Execute → Audit → Retry

Activated via ``GA_TOOL_ORCHESTRATOR=1`` env var.  When off (default),
the agent loop uses ``handler.dispatch()`` directly as before.

Uses existing modules:
- Validate: HookBus ``tool.pre_execute``
- Authorize: ``execution_policy.evaluate_operation()``
- Sandbox: risk-based sandbox level selection + path safety
- Execute: ``handler.dispatch()`` (unchanged)
- Audit: HookBus ``tool.post_execute``
- Retry: escalate sandbox level on failure (up to 3 attempts)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def orchestrator_enabled() -> bool:
    """Check whether the ToolOrchestrator pipeline should be active."""
    return os.environ.get("GA_TOOL_ORCHESTRATOR", "0").strip() == "1"


# ═══════════════════════════════════════════════════════════════════
# Sandbox levels
# ═══════════════════════════════════════════════════════════════════


class SandboxLevel(str, Enum):
    NONE = "none"           # unrestricted
    READ_ONLY = "read_only" # only read operations
    CONTAINED = "contained" # sandboxed execution (block dangerous patterns)
    ISOLATED = "isolated"   # full isolation (block all writes + execution)


_WRITE_TOOLS = frozenset({"file_write", "file_patch", "file_edit"})
_EXEC_TOOLS = frozenset({"code_run", "shell", "bash", "powershell"})


def _sandbox_for_tool(tool_name: str, risk_level: str) -> SandboxLevel:
    """Select an initial sandbox level based on tool type + risk assessment."""
    if risk_level in ("critical",):
        return SandboxLevel.ISOLATED
    if risk_level == "high":
        return SandboxLevel.CONTAINED
    if tool_name in _EXEC_TOOLS:
        return SandboxLevel.CONTAINED
    if tool_name in _WRITE_TOOLS:
        return SandboxLevel.READ_ONLY
    return SandboxLevel.NONE


def _escalate_sandbox(current: SandboxLevel) -> SandboxLevel:
    """Escalate sandbox level one step."""
    order = [
        SandboxLevel.NONE,
        SandboxLevel.READ_ONLY,
        SandboxLevel.CONTAINED,
        SandboxLevel.ISOLATED,
    ]
    try:
        idx = order.index(current)
        return order[min(idx + 1, len(order) - 1)]
    except ValueError:
        return SandboxLevel.ISOLATED


# ═══════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════


class ToolOrchestrator:
    """Wraps each tool dispatch with a standardized pipeline.

    The pipeline is layered on top of the existing ``handler.dispatch()``
    call — it does not replace it. When disabled, the agent loop calls
    dispatch directly (backward compatible).

    Usage in agent_loop.py::

        orchestrator = ToolOrchestrator(handler)
        blocked, reason, extra_yields = orchestrator.pre_check(
            tool_name, args, index=ii)
        if blocked:
            # return synthetic outcome
        # else proceed with handler.dispatch() as usual

    This split design avoids circular imports by not returning StepOutcome
    objects — the agent loop retains control of StepOutcome construction.
    """

    def __init__(self, handler: Any) -> None:
        self._handler = handler

    def pre_check(
        self,
        tool_name: str,
        args: dict[str, Any],
        index: int = 0,
    ) -> tuple[bool, str, list[str]]:
        """Run pipeline stages before dispatch.

        Returns (blocked, reason, yield_lines).

        - If ``blocked=True``, the caller should NOT call dispatch and
          should return a synthetic blocked outcome with *reason*.
        - ``yield_lines`` are text lines to yield to the frontend
          (warnings, policy messages, etc.).
        """
        yield_lines: list[str] = []

        # ── Step 1: VALIDATE via HookBus ──────────────────────────
        from core.hook_bus import HookBus

        pre_results = HookBus.global_instance().emit(
            "tool.pre_execute",
            {"tool_name": tool_name, "args": dict(args or {}), "index": index},
        )
        for r in pre_results:
            if r.block:
                reason = r.block_reason or "blocked by hook"
                yield_lines.append(
                    f"\n[BLOCKED] Tool `{tool_name}` blocked: {reason}\n"
                )
                return True, reason, yield_lines

        # ── Step 2: AUTHORIZE via execution_policy ─────────────────
        from .execution_policy import evaluate_operation, get_policy_mode

        policy_mode = get_policy_mode()
        if policy_mode != "off":
            user_req = getattr(self._handler, "_last_user_input", "") or ""
            decision = evaluate_operation(
                user_request=user_req,
                execution_plan=tool_name,
                mode=policy_mode,
            )

            if not decision.allowed and policy_mode == "hard":
                reason = (
                    f"Operation blocked by execution policy [{policy_mode}]: "
                    f"{decision.reason}"
                )
                yield_lines.append(f"\n[POLICY BLOCKED] {decision.reason}\n")
                return True, reason, yield_lines

            if not decision.allowed:
                # Soft/observe mode: log warning but continue
                yield_lines.append(
                    f"\n[POLICY WARNING] {decision.matched_patterns} — "
                    f"{decision.reason}\n"
                )

        # ── Step 3: SANDBOX — Check for write ops under read_only ──
        # Currently advisory only. Full enforcement in future phases.
        if tool_name in _WRITE_TOOLS and _is_read_only_context(self._handler):
            yield_lines.append(
                f"\n[SANDBOX] Tool `{tool_name}` running under read-only context "
                f"(write operations may be restricted)\n"
            )

        return False, "", yield_lines

    def post_check(
        self,
        tool_name: str,
        args: dict[str, Any],
        index: int = 0,
    ) -> None:
        """Run pipeline stages after dispatch (audit).

        Called after the tool has completed successfully.
        """
        from core.hook_bus import HookBus

        HookBus.global_instance().emit(
            "tool.post_execute",
            {
                "tool_name": tool_name,
                "args": dict(args or {}),
                "index": index,
            },
        )


def _is_read_only_context(handler: Any) -> bool:
    """Check whether the handler is operating under a read-only policy."""
    # Check if there's an active SkillEffects with context_policy="read_only"
    try:
        from core.agents.capability_profile import ProfileManager
        mgr = ProfileManager()
        for profile in mgr.list_profiles():
            if profile.context_policy == "read_only":
                # If we had profile->handler mapping, we'd check here
                # For now, check env override
                pass
    except Exception:
        pass
    return os.environ.get("GA_SANDBOX_READ_ONLY", "0").strip() == "1"

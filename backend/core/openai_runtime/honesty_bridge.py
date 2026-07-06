from __future__ import annotations

from typing import Any

from core.quality import (
    ExecutionAction,
    ExecutionState,
    ResponseClaim,
    StateDelta,
    evaluate_execution_honesty,
    execution_honesty_enabled,
    format_honesty_user_notice,
)

SUCCESS_STATUSES = {"success", "ok", "completed", "done"}


def build_openai_execution_state(
    *,
    execution_actions: list[ExecutionAction],
    executor_execution_state: dict[str, Any],
) -> ExecutionState:
    """Normalize OpenAI orchestration traces into the shared honesty state.

    OpenAI orchestration sees two execution streams: direct OpenAI tool events
    and the nested GenericAgent executor state. The honesty gate should not know
    about either transport shape, so this function is the narrow adapter.
    """

    executor_actions: list[ExecutionAction] = []
    executor_state_delta: dict[str, Any] = {}
    executor_response_claims: list[ResponseClaim] = []
    if isinstance(executor_execution_state, dict):
        for action in executor_execution_state.get("actual_actions") or []:
            if not isinstance(action, dict):
                continue
            executor_actions.append(
                ExecutionAction(
                    tool=str(action.get("tool") or ""),
                    input_summary=str(action.get("input_summary") or ""),
                    output_summary=str(action.get("output_summary") or ""),
                    status=str(action.get("status") or ""),
                    timestamp=str(action.get("timestamp") or ""),
                )
            )
        raw_delta = executor_execution_state.get("state_delta")
        if isinstance(raw_delta, dict):
            executor_state_delta = raw_delta
        for claim in executor_execution_state.get("response_claims") or []:
            if not isinstance(claim, dict):
                continue
            executor_response_claims.append(
                ResponseClaim(
                    claim=str(claim.get("claim") or ""),
                    claim_type=str(claim.get("claim_type") or ""),
                    evidence_status=str(claim.get("evidence_status") or "unsupported"),
                    source=str(claim.get("source") or ""),
                    evidence_type=str(claim.get("evidence_type") or "none"),
                    confidence=float(claim.get("confidence") or 0.0),
                    verified=claim.get("verified"),
                    tolerance=str(claim.get("tolerance") or ""),
                )
            )

    all_actions = list(execution_actions) + executor_actions
    successful_tools = {
        action.tool
        for action in all_actions
        if str(action.status or "").strip().lower() in SUCCESS_STATUSES
    }
    files_changed = tuple(
        str(path)
        for path in (executor_state_delta.get("files_changed") or ())
        if str(path or "").strip()
    )
    checkpoints_updated = bool(executor_state_delta.get("checkpoints_updated"))
    metrics_verified = bool(executor_state_delta.get("metrics_verified")) or (
        "run_genericagent_executor" in successful_tools
    )
    return ExecutionState(
        actual_actions=all_actions,
        state_delta=StateDelta(
            files_changed=files_changed,
            checkpoints_updated=checkpoints_updated,
            metrics_verified=metrics_verified,
        ),
        response_claims=executor_response_claims,
    )


def apply_openai_execution_honesty_gate(
    final_text: str,
    *,
    execution_actions: list[ExecutionAction],
    executor_execution_state: dict[str, Any],
    profiler: Any | None = None,
) -> tuple[str, bool]:
    """Apply the shared execution honesty gate to OpenAI final text."""

    if not execution_honesty_enabled():
        return final_text, False

    execution_state = build_openai_execution_state(
        execution_actions=execution_actions,
        executor_execution_state=executor_execution_state,
    )
    result = evaluate_execution_honesty(final_text, execution_state)
    if profiler is not None:
        try:
            profiler.record_event(
                "execution_honesty_gate",
                kind="quality",
                metadata={
                    "allowed": result.allowed,
                    "findings": [finding.rule for finding in result.findings],
                    "successful_tool_count": sum(
                        1
                        for action in execution_actions
                        if str(action.status or "").strip().lower() in SUCCESS_STATUSES
                    ),
                },
            )
        except Exception:
            pass
    if result.allowed:
        return final_text, False
    return format_honesty_user_notice(result), True


__all__ = [
    "apply_openai_execution_honesty_gate",
    "build_openai_execution_state",
]

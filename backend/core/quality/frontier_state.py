from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .execution_honesty import ExecutionState
from .research_workflow import (
    ResearchWorkflowScore,
    score_research_workflow_response,
    should_inject_research_workflow,
)

AUDIT_TRIGGER_TERMS = (
    "audit",
    "review",
    "manuscript",
    "paper",
    "claim",
    "innovation",
    "innovative",
    "experiment",
    "benchmark",
    "baseline",
    "version",
    "versions",
    "draft",
    "drafts",
    "ablation",
    "heldout",
    "strong conclusion",
    "counterevidence",
    "failure",
)

AUDIT_CONTEXT_TERMS = tuple(
    term for term in AUDIT_TRIGGER_TERMS if term not in {"audit", "review"}
)

AUDIT_TRIGGER_CJK_TERMS = (
    "审计",
    "评审",
    "论文",
    "稿件",
    "创新",
    "实验",
    "基线",
    "版本",
    "强结论",
    "反证",
    "失败",
)

NEGATIVE_CONTROL_TERMS = (
    "hello",
    "what can you do",
    "fix this pytest",
    "fix pytest",
    "read readme",
    "readme first line",
    "read the readme",
)

CANDIDATE_OPERATORS = (
    {
        "name": "Bottleneck-Targeted",
        "summary": "Aim the next move at the current blocking constraint.",
    },
    {
        "name": "Failure-Inversion",
        "summary": "Turn the last failure into a new diagnostic or rule.",
    },
    {
        "name": "Metric-First",
        "summary": "Define the signal of progress before choosing tactics.",
    },
    {
        "name": "Counter-Claim",
        "summary": "Pair strong claims with the strongest plausible opposite claim.",
    },
    {
        "name": "Evidence-Pairing",
        "summary": "Require complementary evidence before mechanism conclusions.",
    },
)


@dataclass(frozen=True)
class FrontierStateSnapshot:
    enabled: bool
    mode: str = ""
    run_id: str = ""
    intent_state: dict[str, Any] = field(default_factory=dict)
    evidence_state: dict[str, Any] = field(default_factory=dict)
    strategy_state: dict[str, Any] = field(default_factory=dict)
    execution_state: dict[str, Any] = field(default_factory=dict)
    synthesis_state: dict[str, Any] = field(default_factory=dict)
    confidence_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalized(text: str | None) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _looks_like_negative_control(query: str, route_target: str | None) -> bool:
    route = _normalized(route_target)
    if _contains_any(query, NEGATIVE_CONTROL_TERMS):
        return True
    if route == "code" and ("fix" in query or "pytest" in query):
        return True
    return False


def frontier_state_should_activate(user_input: str, route_target: str | None = None) -> bool:
    query = _normalized(user_input)
    route = _normalized(route_target)
    if not query or _looks_like_negative_control(query, route):
        return False

    if should_inject_research_workflow(user_input, route_target=route_target):
        return True

    route_signal = route in {"research", "audit", "review", "planner", "planner_executor"}
    audit_action_signal = route_signal or _contains_any(query, ("audit", "review")) or any(
        term in str(user_input or "") for term in ("审计", "评审")
    )
    audit_context_signal = _contains_any(query, AUDIT_CONTEXT_TERMS) or any(
        term in str(user_input or "") for term in AUDIT_TRIGGER_CJK_TERMS if term not in {"审计", "评审"}
    )
    return audit_action_signal and audit_context_signal


def _coerce_execution_state(execution_state: ExecutionState | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(execution_state, ExecutionState):
        return execution_state.to_dict()
    if isinstance(execution_state, dict):
        return dict(execution_state)
    return ExecutionState().to_dict()


def _mode_for(user_input: str, route_target: str | None) -> str:
    route = _normalized(route_target)
    query = _normalized(user_input)
    if route in {"audit", "review"} or _contains_any(query, ("audit", "review")):
        return "audit"
    return "research"


def _task_type(mode: str) -> str:
    return "audit_frontier" if mode == "audit" else "research_frontier"


def _selected_operators(score: ResearchWorkflowScore | None, query: str) -> list[dict[str, str]]:
    if score is None:
        return [dict(CANDIDATE_OPERATORS[0]), dict(CANDIDATE_OPERATORS[2])]

    flags = set(score.bad_strategy_flags)
    selected: list[dict[str, str]] = []
    if "missing_counterevidence_for_strong_claim" in flags:
        selected.append(dict(CANDIDATE_OPERATORS[3]))
    if "missing_version_map" in flags:
        selected.append(
            {
                "name": "Version-Separation",
                "summary": "Build a version map before global synthesis.",
            }
        )
    if "missing_falsifiable_experiment" in flags:
        selected.append(dict(CANDIDATE_OPERATORS[2]))
    if "failed" in query or "failure" in query:
        selected.append(dict(CANDIDATE_OPERATORS[1]))
    if not selected:
        selected = [dict(CANDIDATE_OPERATORS[0]), dict(CANDIDATE_OPERATORS[4])]
    return selected


def _confidence_from_score(score: ResearchWorkflowScore | None, warnings: list[str]) -> str:
    if warnings:
        return "low" if len(warnings) >= 3 else "medium"
    if score is None:
        return "medium"
    if score.total >= 0.8:
        return "high"
    if score.total >= 0.5:
        return "medium"
    return "low"


def _next_verification(score: ResearchWorkflowScore | None, warnings: list[str]) -> list[str]:
    steps: list[str] = []
    if "missing_version_map" in warnings:
        steps.append("Build a version map before combining conclusions.")
    if "missing_counterevidence_for_strong_claim" in warnings:
        steps.append("Run a counter-claim pass for every strong conclusion.")
    if "missing_falsifiable_experiment" in warnings:
        steps.append("Define the smallest falsifiable experiment or kill test.")
    if "missing_evidence_hypothesis_split" in warnings:
        steps.append("Separate verified evidence, user-provided facts, and hypotheses.")
    if not steps:
        steps.append("Carry the strongest surviving claim into the next test.")
    if score and score.missing_sections:
        steps.append("Fill missing workflow sections: " + ", ".join(score.missing_sections[:3]) + ".")
    return steps


def build_frontier_state_snapshot(
    user_input: str,
    route_target: str | None = None,
    response_text: str = "",
    execution_state: ExecutionState | dict[str, Any] | None = None,
    run_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> FrontierStateSnapshot:
    enabled = frontier_state_should_activate(user_input, route_target=route_target)
    mode = _mode_for(user_input, route_target)
    exec_state = _coerce_execution_state(execution_state)
    meta = dict(metadata or {})

    if not enabled:
        return FrontierStateSnapshot(
            enabled=False,
            mode=mode,
            run_id=run_id,
            execution_state=exec_state,
        )

    score: ResearchWorkflowScore | None = None
    if response_text:
        score = score_research_workflow_response(user_input, response_text)

    warnings = list(score.bad_strategy_flags if score is not None else [])
    query = _normalized(user_input)
    selected = _selected_operators(score, query)
    confidence = _confidence_from_score(score, warnings)

    intent_state = {
        "user_goal": str(user_input or "").strip()[:500],
        "task_type": _task_type(mode),
        "route_target": route_target or "",
        "constraints": [
            "Keep the main answer natural.",
            "Expose audit state as expandable context.",
            "Prefer evidence-bound research progress over broad suggestions.",
        ],
        "non_goals": [
            "Do not turn the default answer into YAML.",
            "Do not create a separate agent runtime.",
        ],
    }

    evidence_state = {
        "verified": [],
        "user_provided": ["current user request"],
        "inferred": ["frontier mode: " + mode],
        "unsupported": [],
    }
    if exec_state.get("actual_actions"):
        evidence_state["verified"].append("tool execution trace available")
    if meta.get("audit_context"):
        evidence_state["verified"].append("audit context metadata available")
    if response_text and not exec_state.get("actual_actions"):
        evidence_state["unsupported"].append("response claims still need execution evidence if they assert state changes")

    strategy_state = {
        "candidates": [dict(item) for item in CANDIDATE_OPERATORS],
        "selected": selected,
        "rejected": [
            {
                "name": "Broad suggestion list",
                "reason": "Too much entropy unless tied to a bottleneck and verifier.",
            }
        ],
        "bad_strategy_flags": warnings,
    }

    synthesis_state = {
        "main_claims": [],
        "counterclaims_checked": "missing_counterevidence_for_strong_claim" not in warnings,
        "warnings": warnings,
        "missing_sections": list(score.missing_sections if score is not None else []),
        "section_scores": dict(score.section_scores if score is not None else {}),
        "version_map_required": "missing_version_map" in warnings,
        "gate_action": "review_warn" if warnings else "pass",
    }

    confidence_state = {
        "current_judgment": confidence,
        "high": [],
        "medium": ["frontier state is active for this research/audit task"],
        "low": warnings,
        "next_verification": _next_verification(score, warnings),
        "workflow_score": score.total if score is not None else None,
    }

    return FrontierStateSnapshot(
        enabled=True,
        mode=mode,
        run_id=run_id,
        intent_state=intent_state,
        evidence_state=evidence_state,
        strategy_state=strategy_state,
        execution_state=exec_state,
        synthesis_state=synthesis_state,
        confidence_state=confidence_state,
    )


__all__ = [
    "CANDIDATE_OPERATORS",
    "FrontierStateSnapshot",
    "build_frontier_state_snapshot",
    "frontier_state_should_activate",
]

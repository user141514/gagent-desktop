from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field

RESEARCH_WORKFLOW_ENV_VAR = "GENERIC_AGENT_RESEARCH_WORKFLOW"
RESEARCH_WORKFLOW_MAX_CHARS_ENV_VAR = "GENERIC_AGENT_RESEARCH_WORKFLOW_MAX_CHARS"
RESEARCH_WORKFLOW_REPAIR_ENV_VAR = "GENERIC_AGENT_RESEARCH_WORKFLOW_REPAIR"

REQUIRED_SECTIONS = [
    "Strategy Kernel",
    "System Dynamics Lens",
    "Good/Bad Strategy Audit",
    "Minimal Experiment Ladder",
    "Failure Ledger",
    "Frontier Relay",
]

REQUIRED_AUDIT_GATES = [
    "version_map",
    "strong_counterevidence_check",
    "adversarial_review",
    "time_budget_gate",
]

_RESEARCH_TRIGGERS = [
    "ablation",
    "algorithm",
    "antifragile",
    "bad strategy",
    "baseline",
    "benchmark",
    "bottleneck",
    "claim",
    "claim gate",
    "decision",
    "diagnostic",
    "experiment",
    "failed",
    "failure ledger",
    "frontier",
    "good strategy",
    "hypothesis",
    "innovation",
    "kill test",
    "mechanism",
    "minimal experiment",
    "negative result",
    "open-ended",
    "paper",
    "pivot",
    "research",
    "research strategy",
    "scientific",
    "strategy",
    "system dynamics",
    "workflow",
]

_OPEN_ENDED_TRIGGERS = [
    "next research",
    "next step",
    "what should we try",
    "how should we proceed",
    "choose the next",
    "design a research program",
    "make a plan",
    "turn this into a workflow",
]

_STRONG_RESEARCH_SIGNALS = [
    "ablation",
    "audit",
    "bad strategy",
    "baseline",
    "bottleneck",
    "claim",
    "diagnostic",
    "failed",
    "failure",
    "frontier",
    "innovation",
    "kill test",
    "mechanism",
    "negative result",
    "open-ended",
    "paper",
    "pivot",
    "research",
    "scientific",
    "strong baseline",
    "system dynamics",
]

_READ_EXCLUDES = [
    "read readme first line",
    "readme first line",
    "read the first line",
    "only one sentence",
    "show me the file",
]

_PLAIN_CODE_REVIEW_EXCLUDES = [
    "fix this pytest",
    "fix the failing pytest",
    "implement this function",
    "refactor this file",
    "review this pr",
    "review the pr",
    "security review",
]

_CONTEXT_TEMPLATE = """### Research Workflow Gate
For research/algorithm/benchmark/strategy tasks. Do not quote or summarize source books; apply lenses.

Sections required:
1. Strategy Kernel: diagnosis, guiding policy, coherent next actions; no slogans.
2. System Dynamics Lens: stock/flow, feedback, delay, constraint, leverage.
3. Good/Bad Strategy Audit: baseline, bottleneck, hard choice, evidence, coherent action.
4. Minimal Experiment Ladder: kill test -> diagnostic/ablation -> full benchmark/build.
5. Failure Ledger: hypothesis, observed result, failure type, info bottleneck, implication.
6. Frontier Relay: next handoff = inspect, test, exclude, surviving claim.

Audit gates:
- version_map if multiple dirs/versions/drafts/result sets appear.
- strong_counterevidence_check before "dead feature/no innovation/invalid/does not hold/merely incremental".
- adversarial_review: assume each conclusion is wrong; find strongest counterexample.
- time_budget_gate: report exploration_steps and adversarial_review_steps; if exploration_steps > 0 and adversarial_review_steps = 0, do not final.

Evidence: repo/files/logs/tests/search > memory/summaries > model prior. Mark facts vs assumptions/hypotheses.
"""


@dataclass(frozen=True)
class ResearchWorkflowScore:
    total: float
    section_scores: dict[str, float] = field(default_factory=dict)
    missing_sections: list[str] = field(default_factory=list)
    bad_strategy_flags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def research_workflow_enabled() -> bool:
    value = str(os.environ.get(RESEARCH_WORKFLOW_ENV_VAR, "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def research_workflow_repair_enabled() -> bool:
    value = str(os.environ.get(RESEARCH_WORKFLOW_REPAIR_ENV_VAR, "0")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _contains_any(query: str, phrases: list[str]) -> bool:
    return any(phrase in query for phrase in phrases)


def _effective_max_chars(max_chars: int) -> int:
    limit = max(int(max_chars or 0), 1)
    env_value = os.environ.get(RESEARCH_WORKFLOW_MAX_CHARS_ENV_VAR)
    if env_value:
        try:
            limit = min(limit, max(int(env_value), 1))
        except ValueError:
            pass
    return limit


def should_inject_research_workflow(user_input: str, route_target: str | None = None) -> bool:
    query = " ".join(str(user_input or "").strip().lower().split())
    route = str(route_target or "").strip().lower()
    if not query:
        return False
    if _contains_any(query, _READ_EXCLUDES):
        return False

    has_research_signal = _contains_any(query, _RESEARCH_TRIGGERS) or _contains_any(
        query, _OPEN_ENDED_TRIGGERS
    )
    if not has_research_signal:
        return False

    if route == "code" and not _contains_any(query, _STRONG_RESEARCH_SIGNALS):
        return False
    if route in {"code", "review"} and _contains_any(query, _PLAIN_CODE_REVIEW_EXCLUDES):
        return False
    if route == "review" and "research" not in query and "strategy" not in query:
        return False
    return True


def _truncate_text(text: str, max_chars: int) -> str:
    limit = max(int(max_chars or 0), 1)
    if len(text) <= limit:
        return text
    marker = "\n[truncated]"
    if limit <= len(marker):
        return text[:limit]
    return text[: limit - len(marker)].rstrip() + marker


def build_research_workflow_context(
    user_input: str,
    route_target: str | None,
    max_chars: int = 1800,
) -> dict:
    if not research_workflow_enabled():
        return {
            "block": "",
            "chars": 0,
            "matched": False,
            "reason": "research workflow gate disabled",
            "required_sections": list(REQUIRED_SECTIONS),
            "required_audit_gates": list(REQUIRED_AUDIT_GATES),
        }

    matched = should_inject_research_workflow(user_input, route_target=route_target)
    if not matched:
        return {
            "block": "",
            "chars": 0,
            "matched": False,
            "reason": "query did not match open research workflow triggers",
            "required_sections": list(REQUIRED_SECTIONS),
            "required_audit_gates": list(REQUIRED_AUDIT_GATES),
        }

    block = _truncate_text(_CONTEXT_TEMPLATE, _effective_max_chars(max_chars))
    return {
        "block": block,
        "chars": len(block),
        "matched": True,
        "reason": "matched open research, failed experiment, strategy, or benchmark triggers",
        "required_sections": list(REQUIRED_SECTIONS),
        "required_audit_gates": list(REQUIRED_AUDIT_GATES),
    }


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _section_score(text: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> float:
    if _has_any(text, required) and (not optional or _has_any(text, optional)):
        return 1.0
    if _has_any(text, required + optional):
        return 0.5
    return 0.0


def _needs_version_map(user_text: str) -> bool:
    return _has_any(
        user_text,
        (
            "two versions",
            "multiple versions",
            "old_dir",
            "new_dir",
            "directories",
            "folders",
            "branches",
            "drafts",
            "manuscripts",
            "result sets",
            "v1",
            "v2",
            "多版本",
            "多个版本",
            "两个版本",
            "多个目录",
            "两个目录",
            "旧版",
            "新版",
            "稿件",
            "草稿",
        ),
    ) or bool(re.search(r"\b(?:old|new|v\d+)[_/.-](?:dir|version|draft|result)\b", user_text))


def _has_version_map(text: str) -> bool:
    return _has_any(
        text,
        (
            "version_map",
            "version map",
            "source map",
            "artifact map",
            "version ledger",
            "版本地图",
            "版本图",
            "版本清单",
            "来源地图",
        ),
    )


def _has_strong_conclusion(text: str) -> bool:
    return _has_any(
        text,
        (
            "dead feature",
            "no innovation",
            "not innovative",
            "invalid",
            "does not hold",
            "doesn't hold",
            "only incremental",
            "merely incremental",
            "just incremental",
            "not publishable",
            "feature is dead",
            "死特征",
            "无创新",
            "没有创新",
            "不成立",
            "只是增量",
            "仅是增量",
            "不可发表",
            "死路",
        ),
    )


def _has_counterevidence_check(text: str) -> bool:
    return _has_any(
        text,
        (
            "strong counterevidence",
            "strongest counterevidence",
            "counterevidence check",
            "strongest counterexample",
            "counterexample",
            "opposing evidence",
            "alternate explanation",
            "alternative explanation",
            "反证",
            "最强反证",
            "最强反例",
            "反例",
            "相反证据",
            "替代解释",
        ),
    )


def _has_adversarial_review(text: str) -> bool:
    return _has_any(
        text,
        (
            "adversarial_review",
            "adversarial review",
            "second read",
            "assume each conclusion is wrong",
            "assume every conclusion is wrong",
            "assume the conclusion is wrong",
            "strongest counterexample",
            "strongest counterevidence",
            "二轮重读",
            "反证重读",
            "对抗性重读",
            "假设以上每条结论都是错的",
            "假设每条结论都是错的",
        ),
    )


def _extract_step_count(text: str, names: tuple[str, ...]) -> int | None:
    for name in names:
        pattern = rf"{re.escape(name)}\s*[:=：]\s*(\d+)"
        match = re.search(pattern, text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _time_budget_gate_score(text: str) -> float:
    exploration_steps = _extract_step_count(
        text,
        (
            "exploration_steps",
            "exploration steps",
            "exploration",
            "探索步骤",
        ),
    )
    adversarial_steps = _extract_step_count(
        text,
        (
            "adversarial_review_steps",
            "adversarial review steps",
            "adversarial_review",
            "反证重读步骤",
            "对抗性重读步骤",
        ),
    )
    if exploration_steps is not None and exploration_steps > 0:
        return 1.0 if (adversarial_steps or 0) > 0 else 0.0

    exploration_implied = _has_any(
        text,
        (
            "i checked",
            "i inspected",
            "i verified",
            "i explored",
            "searched",
            "read the",
            "benchmark logs",
            "test output",
            "我检查",
            "我验证",
            "已检查",
            "已验证",
            "搜索",
            "读了",
            "审计",
        ),
    )
    if exploration_implied and not _has_adversarial_review(text):
        return 0.0
    return 1.0


def _bad_strategy_flags(text: str, section_scores: dict[str, float]) -> list[str]:
    flags: list[str] = []
    if section_scores.get("baseline", 0.0) <= 0.0:
        flags.append("missing_baseline")
    if section_scores.get("minimal_experiment", 0.0) <= 0.0:
        flags.append("missing_falsifiable_experiment")
    if _has_any(
        text,
        (
            "better model",
            "comprehensive solution",
            "improve everything",
            "world-class",
            "state of the art solution",
        ),
    ):
        flags.append("generic_goal_language")
    if section_scores.get("evidence_precedence", 0.0) <= 0.0:
        flags.append("missing_evidence_hypothesis_split")
    if section_scores.get("version_map", 1.0) <= 0.0:
        flags.append("missing_version_map")
    if section_scores.get("counterevidence_check", 1.0) <= 0.0:
        flags.append("missing_counterevidence_for_strong_claim")
    if section_scores.get("adversarial_review", 1.0) <= 0.0:
        flags.append("missing_adversarial_review")
    if section_scores.get("time_budget_gate", 1.0) <= 0.0:
        flags.append("missing_adversarial_review_after_exploration")
    return flags


def score_research_workflow_response(
    user_input: str,
    response_text: str,
) -> ResearchWorkflowScore:
    user_text = " ".join(str(user_input or "").strip().lower().split())
    text = " ".join(str(response_text or "").strip().lower().split())
    needs_version_map = _needs_version_map(user_text)
    has_strong_conclusion = _has_strong_conclusion(text)
    section_scores = {
        "strategy_diagnosis": _section_score(
            text,
            ("diagnosis", "bottleneck", "root cause", "strategy"),
            ("guiding", "coherent", "next action", "policy"),
        ),
        "baseline": _section_score(text, ("baseline",)),
        "minimal_experiment": _section_score(
            text,
            ("kill test", "minimal experiment", "diagnostic", "falsifiable"),
            ("experiment", "benchmark", "ablation", "full"),
        ),
        "failure_ledger": _section_score(
            text,
            ("failure ledger", "failure type", "observed result", "failed"),
            ("hypothesis", "implication", "bottleneck"),
        ),
        "evidence_precedence": _section_score(
            text,
            ("evidence", "verified fact", "logs", "test output", "benchmark logs"),
            ("hypothesis", "prior", "model prior", "assumption"),
        ),
        "frontier_relay": _section_score(
            text,
            ("frontier relay", "next handoff", "next relay", "next step"),
            ("inspect", "test", "exclude", "claim"),
        ),
        "version_map": 1.0 if (not needs_version_map or _has_version_map(text)) else 0.0,
        "counterevidence_check": (
            1.0 if (not has_strong_conclusion or _has_counterevidence_check(text)) else 0.0
        ),
        "adversarial_review": 1.0 if _has_adversarial_review(text) else 0.0,
        "time_budget_gate": _time_budget_gate_score(text),
    }

    missing_sections = []
    if section_scores["strategy_diagnosis"] < 0.5:
        missing_sections.append("Strategy Kernel")
    if section_scores["minimal_experiment"] < 0.5:
        missing_sections.append("Minimal Experiment Ladder")
    if section_scores["failure_ledger"] < 0.5:
        missing_sections.append("Failure Ledger")
    if section_scores["evidence_precedence"] < 0.5:
        missing_sections.append("Evidence Precedence")
    if section_scores["frontier_relay"] < 0.5:
        missing_sections.append("Frontier Relay")
    if section_scores["version_map"] < 0.5:
        missing_sections.append("Version Map")
    if section_scores["counterevidence_check"] < 0.5:
        missing_sections.append("Strong Counterevidence Check")
    if section_scores["adversarial_review"] < 0.5:
        missing_sections.append("Adversarial Review")
    if section_scores["time_budget_gate"] < 0.5:
        missing_sections.append("Time Budget Gate")

    bad_flags = _bad_strategy_flags(text, section_scores)
    raw_total = sum(section_scores.values()) / len(section_scores)
    penalty = min(0.5, 0.1 * len(bad_flags))
    total = max(0.0, min(1.0, round(raw_total - penalty, 3)))
    notes = (
        "complete research workflow response"
        if total >= 0.8
        else "missing workflow sections or bad strategy signals"
    )
    return ResearchWorkflowScore(
        total=total,
        section_scores=section_scores,
        missing_sections=missing_sections,
        bad_strategy_flags=bad_flags,
        notes=notes,
    )


__all__ = [
    "REQUIRED_SECTIONS",
    "REQUIRED_AUDIT_GATES",
    "RESEARCH_WORKFLOW_ENV_VAR",
    "RESEARCH_WORKFLOW_MAX_CHARS_ENV_VAR",
    "RESEARCH_WORKFLOW_REPAIR_ENV_VAR",
    "ResearchWorkflowScore",
    "build_research_workflow_context",
    "research_workflow_enabled",
    "research_workflow_repair_enabled",
    "score_research_workflow_response",
    "should_inject_research_workflow",
]

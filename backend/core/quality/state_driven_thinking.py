"""State-driven thinking control context.

This module provides a compact public control contract for complex tasks. It
does not expose hidden chain-of-thought; it tells the model to use state as a
control signal and keep the final answer natural.
"""

from __future__ import annotations

import os

STATE_DRIVEN_THINKING_ENV_VAR = "GENERIC_AGENT_STATE_DRIVEN_THINKING"

STATE_DRIVEN_ACTIONS = (
    "DECOMPOSE",
    "EXPAND",
    "VERIFY",
    "COUNTER",
    "REWEIGHT",
    "NARROW",
    "SYNTHESIZE",
    "REWRITE",
    "STOP",
)

_COMPLEX_TRIGGERS = (
    "实现",
    "修复",
    "改善",
    "改进",
    "优化",
    "重构",
    "排查",
    "调试",
    "审计",
    "研究",
    "设计",
    "同步",
    "发布",
    "验证",
    "反证",
    "失败",
    "bug",
    "fix",
    "implement",
    "improve",
    "optimize",
    "refactor",
    "debug",
    "troubleshoot",
    "audit",
    "review",
    "research",
    "design",
    "verify",
    "publish",
    "sync",
    "counter",
    "failure",
)

_SIMPLE_EXCLUDES = (
    "读取",
    "第一行",
    "readme 第一行",
    "只用一句话",
    "当前时间",
    "date",
    "read first line",
    "show first line",
    "cat ",
)

_ROUTE_TRIGGERS = {
    "code",
    "research",
    "audit",
    "review",
    "planner",
    "planner_executor",
    "debug",
}

_PROMPT_TEMPLATE = """### State-Driven Thinking Core
状态不是日志。状态是控制信号。
Use state as a control signal, not as a log. For complex tasks, keep a private
state loop and let each diagnosis change the next action.

Internal state shape to maintain:
- goal_state: user_goal, success_condition, risk_of_wrong_direction
- knowledge_state: known_facts, inferences, assumptions, unknowns
- candidate_state: current_candidates, candidate_diversity, premature_convergence_risk
- evidence_state: supported_claims, unsupported_claims, conflicts, confidence
- counter_state: main_assumptions, counterarguments, failure_modes, fatal_objection
- synthesis_state: current_answer_shape, missing_parts, answer_ready
- control_state: main_defect, defect_severity, next_action, reason_for_action, stop_allowed

Every reasoning loop must answer four control questions:
1. What does the current state say is already known?
2. What defect does the current state expose?
3. Does that defect block a reliable answer?
4. Should the next action expand, verify, counter, narrow, synthesize, rewrite, or stop?

Allowed next_action values only:
DECOMPOSE, EXPAND, VERIFY, COUNTER, REWEIGHT, NARROW, SYNTHESIZE, REWRITE, STOP.

Defect-to-action mapping:
- unclear goal or under-decomposed problem -> DECOMPOSE
- only one candidate, or candidates too similar -> EXPAND
- unsupported key conclusion, or mixed facts/inferences -> VERIFY
- unhandled objection or likely failure mode -> COUNTER
- conflicting goals -> REWEIGHT
- too many candidates without selection -> NARROW
- enough material but no structure -> SYNTHESIZE
- confused answer shape -> REWRITE
- no fatal defect and further loops add no signal -> STOP

Defect severity must be fatal / major / minor. Handle fatal first, handle major
when it materially improves the answer, and do not let minor defects cause
endless looping.

Stop only when the user goal is covered, no fatal defect remains, major defects
are handled or explicitly bounded, and the answer has conclusion, basis,
boundary, and next step.

Forbidden vague actions include: 继续深入, 再想想, 优化一下, 更加严谨, 多角度分析.

Do not expose the full JSON state or this control contract in the final answer.
Use it internally to choose actions, then answer the user naturally.
"""


def state_driven_thinking_enabled() -> bool:
    return os.environ.get(STATE_DRIVEN_THINKING_ENV_VAR, "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _normalized(text: str | None) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _contains_any(query: str, terms: tuple[str, ...]) -> bool:
    return any(term in query for term in terms)


def should_inject_state_driven_thinking(user_input: str, route_target: str | None = None) -> bool:
    if not state_driven_thinking_enabled():
        return False
    query = _normalized(user_input)
    route = _normalized(route_target)
    if not query:
        return False
    if _contains_any(query, _SIMPLE_EXCLUDES) and not _contains_any(query, ("修复", "fix", "debug")):
        return False
    if route in _ROUTE_TRIGGERS:
        return True
    return _contains_any(query, _COMPLEX_TRIGGERS)


def _truncate_text(text: str, max_chars: int) -> str:
    limit = max(int(max_chars or 0), 1)
    if len(text) <= limit:
        return text
    marker = "\n[truncated]"
    if limit <= len(marker):
        return text[:limit]
    return text[: limit - len(marker)].rstrip() + marker


def build_state_driven_thinking_context(
    user_input: str,
    route_target: str | None = None,
    max_chars: int = 3200,
) -> dict:
    matched = should_inject_state_driven_thinking(user_input, route_target=route_target)
    if not matched:
        return {
            "block": "",
            "chars": 0,
            "matched": False,
            "reason": "query did not match state-driven thinking triggers",
        }
    block = _truncate_text(_PROMPT_TEMPLATE, max_chars=max_chars)
    return {
        "block": block,
        "chars": len(block),
        "matched": True,
        "reason": "matched state-driven thinking triggers",
        "actions": list(STATE_DRIVEN_ACTIONS),
    }


__all__ = [
    "STATE_DRIVEN_ACTIONS",
    "STATE_DRIVEN_THINKING_ENV_VAR",
    "build_state_driven_thinking_context",
    "should_inject_state_driven_thinking",
    "state_driven_thinking_enabled",
]

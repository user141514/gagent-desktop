"""Clarification Gate – restrict unnecessary ask_user calls.

Design principles:
- Default: deny ask_user. The agent should proceed with minimal assumptions.
- Only allow ask_user when: safety/irreversible, missing critical target,
  equiprobable candidates with divergent actions, extreme cost differences,
  or privacy/permission issues.
- When denied, return a fallback_instruction so the model can continue,
  instead of failing outright.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

CLARIFICATION_GATE_ENV_VAR = "GENERIC_AGENT_CLARIFICATION_GATE"

# ── Question-form markers (downgrades A-rule danger) ──────────────
_QUESTION_MARKERS = [
    "怎么", "如何", "哪种", "什么方式", "什么方法",
    "怎样", "哪一", "哪个",
    "how to", "how do", "how should", "which way",
    "what is the best", "what's the best",
    "推荐", "建议", "方案",
]


def _is_question_about_danger(user_input: str) -> bool:
    """Check if the user is asking about a dangerous topic, not requesting it."""
    return _contains_any(user_input.lower(), _QUESTION_MARKERS)


# ── Rule A: Safety / Irreversible keywords ─────────────────────────

_DANGER_KEYWORDS = [
    "删除", "删掉", "移除", "清空",
    "覆盖", "重写全部", "全部覆盖",
    "drop", "rm -rf", "rm -r", "rmdir",
    "deploy", "部署", "上线", "发布",
    "push", "commit", "merge",
    "reset --hard", "reset", "wipe",
    "格式化", "format",
    "销毁", "永久删除",
    "drop table", "drop database",
    "truncate", "清空表",
    "force push", "强制推送",
    "revoke", "吊销",
    "delete", "删除记录",
    "uninstall", "卸载",
    "purge", "清除",
]

# ── Rule B: Missing critical object markers ────────────────────────

# Full action-phrase patterns that indicate the user didn't specify a target.
# These are vague commands that lack a direct object.
_MISSING_TARGET_PHRASES = [
    "帮我改一下", "处理一下", "修一下",
    "优化一下", "改一下", "弄一下",
    "fix it", "change it", "update it",
    "modify it", "optimize it",
    "帮我改改", "帮我看一下", "帮我看看",
    "帮我处理", "帮我修复",
    "搞一下", "调一下",
]

# Very short ambiguous references — pronouns without clear antecedent.
# Only matched when the input is short (< 20 chars) and has no clear
# object noun following the pronoun.
_SHORT_AMBIGUOUS_PRONOUNS = [
    "这个", "那个", "它", "这个怎么", "那个怎么",
    "这是什么", "那是什么",
    "this one", "that one",
]

# ── Rule D: Probing question patterns (should be denied) ────────────

_PROBING_QUESTION_MARKERS = [
    "你想", "您想", "你要", "您要",
    "你想优化", "您想优化",
    "你想改", "您想改",
    "哪个", "哪一种", "什么样的",
    "which one", "which part", "what kind",
    "你想怎么", "您想怎么",
    "你想如何", "您想如何",
    "前端还是后端", "后端还是前端",
    "你想先",
    "do you want", "would you like",
    "which would you",
]


def clarification_gate_enabled() -> bool:
    return str(os.environ.get(CLARIFICATION_GATE_ENV_VAR, "")).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ClarificationDecision:
    allowed: bool
    reason: str
    risk_level: str  # "none" | "low" | "medium" | "high" | "critical"
    confidence_gap: float | None = None
    fallback_instruction: str = ""
    signals: list[str] = field(default_factory=list)


def _contains_any(text: str, phrases: list[str]) -> bool:
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in phrases)


def _user_input_preview(user_input: str, max_chars: int = 200) -> str:
    text = str(user_input or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _question_preview(question: str, max_chars: int = 300) -> str:
    text = str(question or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


# ── Main gate function ─────────────────────────────────────────────


def should_allow_clarification(
    user_input: str,
    question: str,
    context: dict | None = None,
) -> ClarificationDecision:
    """Determine whether an ask_user call should be allowed.

    Args:
        user_input: The original user request.
        question: The question the agent wants to ask the user.
        context: Optional context dict that may contain:
            - target_file: str | None
            - target_object: str | None
            - selected_candidate: str | None
            - candidates: list[dict] with keys {name, score, action}
            - known_scope: bool

    Returns:
        ClarificationDecision with allowed/reason/risk_level/fallback_instruction.
    """
    ctx = dict(context or {})
    signals: list[str] = []
    user_lower = str(user_input or "").strip().lower()
    question_lower = str(question or "").strip().lower()

    # ── Rule A: Safety / Irreversible ──────────────────────────────
    if _contains_any(user_lower, _DANGER_KEYWORDS):
        # If the user is asking a question about a dangerous topic
        # (e.g. "用哪种方式部署？"), don't treat it as dangerous.
        if _is_question_about_danger(user_input):
            signals.append("danger_keyword_in_question")
            # fall through — don't trigger Rule A
        else:
            has_target = bool(
                ctx.get("target_file")
                or ctx.get("target_object")
                or ctx.get("selected_candidate")
            )
            if not has_target:
                signals.append("danger_keyword_no_target")
                return ClarificationDecision(
                    allowed=True,
                    reason="A: safety/irreversible keyword matched; target is missing",
                    risk_level="high",
                    signals=signals,
                    fallback_instruction=(
                        "危险操作缺少明确目标。请确认操作对象后重新调用。"
                    ),
                )

            signals.append("danger_keyword_with_target")
            return ClarificationDecision(
                allowed=False,
                reason="A: safety keyword matched but target is present — proceed carefully",
                risk_level="medium",
                signals=signals,
                fallback_instruction=(
                    "检测到危险操作关键词。目标已明确，请谨慎执行。"
                    "如仍不确定范围，请先做最小可逆操作确认。"
                ),
            )

    # ── Rule B: Missing critical object ────────────────────────────
    has_target = bool(
        ctx.get("target_file")
        or ctx.get("target_object")
        or ctx.get("selected_candidate")
    )

    # B1: Vague action phrases without a clear target object
    # "帮我改一下" (5 chars, no object) → ambiguous
    # "帮我看看这个项目的结构" (10 chars, with "这个项目") → has target
    if _contains_any(user_lower, _MISSING_TARGET_PHRASES) and not has_target:
        # Check if the input has meaningful content beyond the vague phrase.
        # If there's a target noun phrase (e.g. "这个项目", "那个文件"),
        # the input is not truly ambiguous.
        _stripped = user_input.strip()
        _has_object_hint = bool(
            re.search(r"(?:这个|那个|这些|那些|某个)\s*[\u4e00-\u9fff]{2,}", _stripped)
            or len(_stripped) >= 15  # longer input likely contains context
        )
        if not _has_object_hint:
            signals.append("vague_action_no_target")
            return ClarificationDecision(
                allowed=True,
                reason="B1: vague action phrase detected; no target in context",
                risk_level="medium",
                signals=signals,
                fallback_instruction=(
                    "无法确定操作目标。请用户明确指定对象后重试。"
                ),
            )
        signals.append("vague_action_target_resolved")

    # B2: Ambiguous pronouns without a following target noun
    # "这个项目" / "那个文件" → resolved (pronoun + noun forms a target)
    # "这个" alone / "这个怎么" / "这是什么" → ambiguous
    _resolved_pronoun = bool(re.search(r"(?:这个|那个|它|他|她)\s*[\u4e00-\u9fff]{2,}", user_input))
    if not _resolved_pronoun and _contains_any(user_lower, _SHORT_AMBIGUOUS_PRONOUNS):
        if not has_target:
            signals.append("ambiguous_pronoun_no_target")
            return ClarificationDecision(
                allowed=True,
                reason="B2: ambiguous pronoun without clear target noun; no target in context",
                risk_level="medium",
                signals=signals,
                fallback_instruction=(
                    "输入包含模糊代词且未明确目标对象。请用户明确指定操作目标。"
                ),
            )
        signals.append("pronoun_target_resolved")

    # ── Rule D: Probing questions — deny by default ────────────────
    if _contains_any(question_lower, _PROBING_QUESTION_MARKERS):
        # Check if this is truly necessary (rules A/B already handled above)
        signals.append("probing_question_denied")
        return ClarificationDecision(
            allowed=False,
            reason="D: question probes user preference when agent can infer from state",
            risk_level="low",
            signals=signals,
            fallback_instruction=(
                "不要反问用户偏好。请根据现有信息做最小假设，先分析当前状态再给出建议。"
                "如果确实需要用户决策，提供具体的可选项和推荐方案，而不是泛泛地问'你想优化哪部分'。"
            ),
        )

    # ── Rule C: Equiprobable candidates with divergent actions ─────
    candidates = ctx.get("candidates") or []
    if isinstance(candidates, list) and len(candidates) >= 2:
        sorted_candidates = sorted(
            candidates,
            key=lambda c: float(c.get("score", 0)),
            reverse=True,
        )
        if len(sorted_candidates) >= 2:
            top1 = sorted_candidates[0]
            top2 = sorted_candidates[1]
            score1 = float(top1.get("score", 0))
            score2 = float(top2.get("score", 0))
            gap = abs(score1 - score2)
            action1 = str(top1.get("action", "")).strip()
            action2 = str(top2.get("action", "")).strip()

            if gap < 0.15 and action1 and action2 and action1 != action2:
                signals.append("equiprobable_divergent_candidates")
                return ClarificationDecision(
                    allowed=True,
                    reason=(
                        f"C: top-2 candidates {score1} vs {score2} "
                        f"(gap={gap:.3f}) with divergent actions "
                        f"({action1} vs {action2})"
                    ),
                    risk_level="medium",
                    confidence_gap=round(gap, 4),
                    signals=signals,
                    fallback_instruction=(
                        "多个候选方案概率接近且行动分叉明显。请用户确认方向后继续。"
                    ),
                )

            if gap >= 0.15:
                signals.append("clear_winner")
            else:
                signals.append("same_action_or_empty")

    # ── Rule E (implied): Extreme cost difference ──────────────────
    # Check context for cost signals
    cost_signal = ctx.get("cost_ratio") or ctx.get("cost_difference")
    if cost_signal is not None:
        try:
            ratio = float(cost_signal)
            if ratio > 5.0:
                signals.append("extreme_cost_difference")
                return ClarificationDecision(
                    allowed=True,
                    reason=f"E: cost ratio {ratio:.1f}x exceeds threshold",
                    risk_level="medium",
                    signals=signals,
                    fallback_instruction=(
                        f"不同方案成本差异达 {ratio:.1f} 倍。请确认是否接受高成本方案。"
                    ),
                )
        except (ValueError, TypeError):
            pass

    # ── Rule F (implied): Privacy / Permission ─────────────────────
    privacy_signal = ctx.get("requires_privacy_check") or ctx.get("requires_permission")
    if privacy_signal:
        signals.append("privacy_permission_required")
        return ClarificationDecision(
            allowed=True,
            reason="F: privacy or permission check required by context",
            risk_level="high",
            signals=signals,
            fallback_instruction=(
                "此操作涉及隐私或权限问题。请确认授权后继续。"
            ),
        )

    # ── Default: deny ──────────────────────────────────────────────
    if not signals:
        signals.append("default_deny")

    return ClarificationDecision(
        allowed=False,
        reason="default: no trigger condition met; agent should proceed with assumptions",
        risk_level="low",
        signals=signals,
        fallback_instruction=(
            "默认不反问用户。请基于现有信息做最小、可逆的假设继续推进。"
            "如果你确实缺少关键信息，先尝试通过工具（文件读取、代码分析等）获取。"
            "只有在安全风险、不可逆操作、缺失关键目标时才可以再次尝试 ask_user。"
        ),
    )


# ── Profiler event helpers ────────────────────────────────────────


def _emit_clarification_event(
    profiler,
    event_name: str,
    decision: ClarificationDecision,
    user_input: str,
    question: str,
) -> str | None:
    """Record a clarification gate event in the profiler if available."""
    if profiler is None:
        return None
    try:
        return profiler.record_event(
            name=event_name,
            kind="tool",
            metadata={
                "reason": decision.reason,
                "risk_level": decision.risk_level,
                "signals": decision.signals,
                "question_chars": len(str(question or "")),
                "user_input_preview": _user_input_preview(user_input, max_chars=300),
            },
        )
    except Exception:
        return None


def emit_clarification_requested(
    profiler,
    decision: ClarificationDecision,
    user_input: str,
    question: str,
) -> str | None:
    return _emit_clarification_event(
        profiler, "clarification_requested", decision, user_input, question
    )


def emit_clarification_allowed(
    profiler,
    decision: ClarificationDecision,
    user_input: str,
    question: str,
) -> str | None:
    return _emit_clarification_event(
        profiler, "clarification_allowed", decision, user_input, question
    )


def emit_clarification_denied(
    profiler,
    decision: ClarificationDecision,
    user_input: str,
    question: str,
) -> str | None:
    return _emit_clarification_event(
        profiler, "clarification_denied", decision, user_input, question
    )

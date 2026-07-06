"""Rule-based early-stop helpers for the classic executor."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


EARLY_STOP_ENV_VAR = "GENERIC_AGENT_EARLY_STOP"

_CONCISE_REQUEST_PHRASES = (
    "只用一句话",
    "一句话总结",
    "一句话概括",
    "只给结论",
    "只给答案",
    "简短回答",
    "简短说明",
    "只要标题",
    "只要第一行",
    "只给标题",
    "一句话",
    "concise",
    "one sentence",
    "short answer",
    "just the title",
    "just the conclusion",
)

_TITLE_REQUEST_PHRASES = (
    "标题",
    "第一行",
    "title",
    "headline",
)

_SUMMARY_REQUEST_PHRASES = (
    "总结一下",
    "总结全文",
    "做个总结",
    "概括一下",
    "概述",
    "summarize the",
    "tl;dr",
    "tldr",
)

_EXPLAIN_REQUEST_PHRASES = (
    "解释",
    "说明",
    "explain",
    "describe",
)

_ACTION_REQUEST_PHRASES = (
    "修改",
    "修复",
    "实现",
    "编写",
    "写入",
    "运行测试",
    "执行测试",
    "安装",
    "启动",
    "run test",
    "run tests",
    "modify",
    "edit",
    "patch",
    "write file",
    "implement",
    "fix",
    "install",
    "start",
)

_CONTINUE_PHRASES = (
    "继续读取",
    "继续搜索",
    "继续运行",
    "继续修改",
    "继续查看",
    "继续处理",
    "还需要",
    "下一步",
    "todo",
    "待办",
    "需要继续",
    "让我继续",
    "我需要继续",
    "需要调用",
    "need to continue",
    "continue reading",
    "continue searching",
    "continue running",
    "next step",
    "todo",
    "need to",
)

_PLAN_ONLY_PHRASES = (
    "让我先",
    "先分析",
    "先检查",
    "先读取",
    "执行计划",
    "计划如下",
    "分析策略",
    "我会先",
    "i will first",
    "let me first",
    "plan:",
)

_COMPLETION_PHRASES = (
    "已完成",
    "任务完成",
    "已经完成",
    "最终答案",
    "以上是完整",
    "以上就是",
    "complete",
    "completed",
    "final answer",
    "task complete",
    "done",
)

_FAILURE_PHRASES = (
    "error:",
    "traceback",
    "[error]",
    "\"status\": \"error\"",
    "'status': 'error'",
    "失败",
    "异常",
    "超时",
)


def early_stop_enabled() -> bool:
    return str(os.environ.get(EARLY_STOP_ENV_VAR, "")).strip() == "1"


@dataclass
class EarlyStopDecision:
    should_stop: bool
    reason: str
    confidence: float
    signals: dict[str, Any] = field(default_factory=dict)


def _normalize_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _sentence_count(text: str) -> int:
    stripped = re.sub(r"<[^>]+>", " ", str(text or ""))
    parts = re.split(r"[。！？!?]+|(?<!\.)\.(?!\.)", stripped)
    return len([part for part in parts if part.strip()])


def _extract_summary_text(text: str) -> str:
    match = re.search(r"<summary>(.*?)</summary>", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return str(text or "").strip()


def _tool_results_text(tool_results: list | None) -> str:
    pieces: list[str] = []
    for item in tool_results or []:
        if isinstance(item, dict):
            content = item.get("content")
            if content is not None:
                pieces.append(str(content))
        elif item is not None:
            pieces.append(str(item))
    return "\n".join(piece for piece in pieces if piece).strip()


def _looks_like_title_answer(text: str) -> bool:
    if re.search(r"(?m)^#\s+\S+", text):
        return True
    lowered = _normalize_text(text)
    return "标题" in lowered or "title" in lowered


def _looks_like_plan_only(text: str, completion_markers: bool) -> bool:
    lowered = _normalize_text(text)
    if completion_markers:
        return False
    if _contains_any(lowered, _PLAN_ONLY_PHRASES):
        return True
    return lowered.startswith(("计划", "步骤", "先", "first,", "first ", "let me"))


def _response_has_effective_answer(
    user_text: str,
    assistant_text: str,
    summary_text: str,
    concise_request: bool,
) -> tuple[bool, dict[str, bool]]:
    lowered_user = _normalize_text(user_text)
    lowered_assistant = _normalize_text(assistant_text)
    summary_lower = _normalize_text(summary_text)
    requested_title = _contains_any(lowered_user, _TITLE_REQUEST_PHRASES)
    requested_summary = _contains_any(lowered_user, _SUMMARY_REQUEST_PHRASES)
    explain_request = _contains_any(lowered_user, _EXPLAIN_REQUEST_PHRASES)
    sentence_count = _sentence_count(summary_text)
    title_answer = requested_title and _looks_like_title_answer(assistant_text)
    summary_answer = requested_summary and (
        _contains_any(summary_lower, ("定位", "总结", "workbench", "built on top of", "multi-agent", "项目"))
        or sentence_count >= 1
    )
    explain_answer = explain_request and len(summary_text.strip()) >= 80 and sentence_count >= 2
    generic_answer = len(summary_text.strip()) >= 120 and sentence_count >= 2
    concise_answer = concise_request and len(summary_text.strip()) >= 20 and sentence_count <= 3
    has_effective_answer = (
        (title_answer and (summary_answer or concise_answer))
        or explain_answer
        or (concise_answer and requested_summary)
        or (generic_answer and not requested_title and not requested_summary)
    )
    return has_effective_answer, {
        "requested_title": requested_title,
        "requested_summary": requested_summary,
        "explain_request": explain_request,
        "title_answer": title_answer,
        "summary_answer": summary_answer,
        "generic_answer": generic_answer,
        "concise_answer": concise_answer,
        "sentence_count": sentence_count,
    }


def should_stop_classic_executor(
    user_input: str,
    last_assistant_text: str,
    tool_results: list | None = None,
    turn_index: int | None = None,
    metadata: dict | None = None,
) -> EarlyStopDecision:
    user_text = str(user_input or "")
    assistant_text = str(last_assistant_text or "")
    metadata = dict(metadata or {})
    lowered_user = _normalize_text(user_text)
    lowered_assistant = _normalize_text(assistant_text)
    summary_text = _extract_summary_text(assistant_text)
    tool_text = _tool_results_text(tool_results)
    lowered_tool_text = _normalize_text(tool_text)

    concise_request = _contains_any(lowered_user, _CONCISE_REQUEST_PHRASES)
    action_request = _contains_any(lowered_user, _ACTION_REQUEST_PHRASES)
    completion_markers = ("<summary>" in lowered_assistant) or _contains_any(lowered_assistant, _COMPLETION_PHRASES)
    continue_markers = _contains_any(lowered_assistant, _CONTINUE_PHRASES)
    plan_only = _looks_like_plan_only(assistant_text, completion_markers)
    tool_failure = _contains_any(lowered_tool_text, _FAILURE_PHRASES)
    required_steps_completed = metadata.get("required_steps_completed")
    turn_value = int(turn_index or 0)
    tool_results_ready = bool(tool_text.strip()) and not tool_failure
    has_effective_answer, answer_signals = _response_has_effective_answer(
        user_text,
        assistant_text,
        summary_text,
        concise_request,
    )
    completion_like = completion_markers or (
        has_effective_answer
        and turn_value >= 2
    )

    signals: dict[str, Any] = {
        "concise_request": concise_request,
        "action_request": action_request,
        "completion_markers": completion_markers,
        "continue_markers": continue_markers,
        "plan_only": plan_only,
        "tool_failure": tool_failure,
        "tool_results_ready": tool_results_ready,
        "turn_index": turn_value,
        "required_steps_completed": required_steps_completed,
        "assistant_chars": len(assistant_text),
        "summary_chars": len(summary_text),
        **answer_signals,
    }

    if not assistant_text.strip():
        return EarlyStopDecision(False, "assistant_text_empty", 0.0, signals)
    if required_steps_completed is False:
        return EarlyStopDecision(False, "required_steps_incomplete", 0.05, signals)
    if tool_failure:
        return EarlyStopDecision(False, "tool_failure_unresolved", 0.05, signals)
    if continue_markers:
        return EarlyStopDecision(False, "assistant_requested_continuation", 0.05, signals)
    if action_request and required_steps_completed is not True:
        return EarlyStopDecision(False, "execution_task_requires_more_steps", 0.1, signals)
    if plan_only and not completion_markers:
        return EarlyStopDecision(False, "assistant_output_is_plan_only", 0.1, signals)
    if len(summary_text.strip()) < 20:
        return EarlyStopDecision(False, "assistant_answer_too_short", 0.1, signals)
    if turn_value < 2 and not completion_markers:
        return EarlyStopDecision(False, "turn_too_early_without_completion_markers", 0.15, signals)
    if not completion_like:
        return EarlyStopDecision(False, "no_strong_completion_signal", 0.2, signals)

    confidence = 0.45
    if concise_request:
        confidence += 0.1
    if completion_markers:
        confidence += 0.2
    if has_effective_answer:
        confidence += 0.2
    if tool_results_ready:
        confidence += 0.1
    if turn_value >= 2:
        confidence += 0.05
    confidence = round(min(confidence, 0.98), 3)

    reasons = []
    if completion_markers:
        reasons.append("completion_markers_present")
    if has_effective_answer:
        reasons.append("assistant_answer_matches_request")
    if tool_results_ready:
        reasons.append("tool_results_ready")
    if concise_request:
        reasons.append("concise_request")
    if turn_value >= 2:
        reasons.append("turn_ge_2")
    reason = ",".join(reasons) or "rule_based_completion_detected"
    return EarlyStopDecision(True, reason, confidence, signals)

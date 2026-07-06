"""Narrow direct-answer helpers for simple read/extract tasks."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


DIRECT_ANSWER_ENV_VAR = "GENERIC_AGENT_DIRECT_ANSWER"

_BANNED_ACTION_PHRASES = (
    "修改",
    "实现",
    "修复",
    "写入",
    "patch",
    "edit",
    "modify",
    "fix",
    "run tests",
    "运行测试",
    "执行测试",
    "安装",
    "启动",
    "部署",
    "deploy",
    "install",
    "start",
)

_BANNED_COMPLEX_PHRASES = (
    # Only ban requests that genuinely require multi-step reasoning.
    # Simple "read and show" requests with words like 分析/解释 are fine.
    "详细分析",
    "架构审查",
    "优化",
    "重构",
    "对比多个",
    "对比两个",
    "多个文件",
    "多文件",
    "综合分析",
    "全文总结",
    "完整内容",
    "whole file",
    "full file",
    "optimize",
    "refactor",
    "compare multiple",
    "execution flow",
    "code structure",
)

_READ_HINTS = (
    "读取",
    "查看",
    "看看",
    "打开",
    "显示",
    "抽取",
    "提取",
    "read",
    "extract",
    "show",
    "open",
    "view",
)

_FIRST_LINE_HINTS = (
    "第一行",
    "title",
    "标题",
    "headline",
    "first line",
)

_SUMMARY_HINTS = (
    "一句话总结",
    "一句话概括",
    "概括",
    "summary",
)

_FIELD_HINTS = (
    "版本号",
    "version",
    "项目名",
    "project name",
)

_FAILURE_PHRASES = (
    "error:",
    "\"status\": \"error\"",
    "'status': 'error'",
    "[error]",
    "traceback",
    "失败",
    "异常",
)


def direct_answer_enabled() -> bool:
    return str(os.environ.get(DIRECT_ANSWER_ENV_VAR, "")).strip() == "1"


@dataclass
class DirectAnswerDecision:
    should_answer: bool
    answer: str | None
    reason: str
    confidence: float
    signals: dict[str, Any] = field(default_factory=dict)


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _tool_results_text(tool_results: list | None) -> str:
    parts = []
    for item in tool_results or []:
        if isinstance(item, dict) and item.get("content") is not None:
            parts.append(str(item.get("content")))
        elif item is not None:
            parts.append(str(item))
    return "\n".join(part for part in parts if part).strip()


def _meaningful_lines(text: str) -> list[str]:
    lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[FILE]") or line.startswith("由于设置了show_linenos"):
            continue
        line = re.sub(r"^\d+\|", "", line).strip()
        if not line or line == "```":
            continue
        lines.append(line)
    return lines


def _extract_markdown_title(text: str) -> str | None:
    for line in _meaningful_lines(text):
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None


def _extract_first_nonempty(text: str) -> str | None:
    lines = _meaningful_lines(text)
    return lines[0] if lines else None


def _strip_markup(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("`", " ")
    value = value.replace("*", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_requested_line_count(text: str, default: int = 80) -> int:
    for pattern in (
        r"前\s*(\d+)\s*行",
        r"first\s*(\d+)\s*lines?",
    ):
        match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
        if match:
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                continue
            return max(1, min(value, 200))
    return default


def _extract_explicit_target_label(text: str) -> str | None:
    path_pattern = (
        r"(?<![\w.-])"
        r"([A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+\.(?:py|md|txt|json|yaml|yml|toml))"
        r"(?![\w.-])"
    )
    file_pattern = (
        r"(?<![\w.-])"
        r"(README(?:\.md|\.txt)?|[A-Za-z0-9_.-]+\.(?:py|md|txt|json|yaml|yml|toml))"
        r"(?![\w.-])"
    )
    for pattern in (r"`([^`]+)`", path_pattern, file_pattern):
        match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
        if match:
            return str(match.group(1)).strip().replace("\\", "/")
    return None


def _clean_view_block(text: str) -> str:
    cleaned: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("由于设置了show_linenos"):
            continue
        if stripped == "```":
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _extract_positioning_sentence(text: str, title: str | None) -> str | None:
    """Extract a generic one-line project description from README text.

    Returns a short positioning sentence, or None if nothing reliable found.
    """
    clean_lines = [_strip_markup(line) for line in _meaningful_lines(text)]
    title_lower = _normalize(title)
    for line in clean_lines:
        lowered = _normalize(line)
        normalized_line = lowered.lstrip("#").strip()
        if not lowered or normalized_line == title_lower:
            continue
        # Generic pattern: "X is a Y built on top of Z" or "X is a Y workbench"
        if title and any(phrase in lowered for phrase in (
            "is a", "是一个", "built on top of", "基于",
            "workbench", "工作台", "framework", "框架",
        )):
            return f"《{title}》是一个项目工作台/框架。"
    return None


def _extract_version(text: str) -> str | None:
    for line in _meaningful_lines(text):
        match = re.search(r"\b(?:v|version[:\s]*)?(\d+\.\d+(?:\.\d+)*)\b", line, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def try_direct_answer_from_tool_result(
    user_input: str,
    tool_results: list | None,
    metadata: dict | None = None,
) -> DirectAnswerDecision:
    metadata = dict(metadata or {})
    user_text = str(user_input or "")
    lowered_user = _normalize(user_text)
    tool_text = _tool_results_text(tool_results)
    lowered_tool = _normalize(tool_text)
    tool_names = [str(name).strip() for name in (metadata.get("tool_names") or []) if str(name).strip()]
    extraction_type = str(metadata.get("extraction_type") or "").strip()

    signals: dict[str, Any] = {
        "tool_names": tool_names,
        "tool_result_count": len(tool_results or []),
        "tool_result_chars": len(tool_text),
        "is_read_request": _contains_any(lowered_user, _READ_HINTS),
        "asks_first_line": _contains_any(lowered_user, _FIRST_LINE_HINTS),
        "asks_summary": _contains_any(lowered_user, _SUMMARY_HINTS),
        "asks_field": _contains_any(lowered_user, _FIELD_HINTS),
        "mentions_readme": "readme" in lowered_user,
        "extraction_type": extraction_type,
    }

    if not tool_text.strip():
        return DirectAnswerDecision(False, None, "tool_results_empty", 0.0, signals)
    if _contains_any(lowered_user, _BANNED_ACTION_PHRASES):
        return DirectAnswerDecision(False, None, "action_request_not_supported", 0.0, signals)
    if _contains_any(lowered_user, _BANNED_COMPLEX_PHRASES):
        return DirectAnswerDecision(False, None, "complex_request_not_supported", 0.0, signals)
    if _contains_any(lowered_tool, _FAILURE_PHRASES):
        return DirectAnswerDecision(False, None, "tool_result_failure", 0.0, signals)
    if not signals["is_read_request"]:
        return DirectAnswerDecision(False, None, "not_read_extract_request", 0.0, signals)
    if tool_names and any(name not in {"file_read", "code_run"} for name in tool_names):
        return DirectAnswerDecision(False, None, "unsupported_tool_mix", 0.1, signals)
    if tool_names and "file_read" not in tool_names:
        return DirectAnswerDecision(False, None, "file_read_required", 0.1, signals)

    if extraction_type.startswith("explicit_file_view"):
        line_count = int(metadata.get("line_count") or _extract_requested_line_count(user_text, default=80))
        target_label = str(metadata.get("target_label") or "").strip() or _extract_explicit_target_label(user_text) or ""
        clean_block = _clean_view_block(tool_text)
        signals["line_count"] = line_count
        signals["target_label"] = target_label
        if not clean_block:
            return DirectAnswerDecision(False, None, "explicit_file_view_empty", 0.0, signals)
        header = f"已读取 `{target_label}` 前 {line_count} 行：" if target_label else f"已读取文件前 {line_count} 行："
        answer = f"{header}\n\n```text\n{clean_block}\n```"
        return DirectAnswerDecision(True, answer, "explicit_file_view", 0.95, signals)

    title = _extract_markdown_title(tool_text)
    first_line = _extract_first_nonempty(tool_text)
    version = _extract_version(tool_text)

    if signals["mentions_readme"] and signals["asks_first_line"]:
        extracted_title = title or first_line
        if not extracted_title:
            return DirectAnswerDecision(False, None, "title_not_found", 0.15, signals)
        positioning = None
        if signals["asks_summary"]:
            positioning = _extract_positioning_sentence(tool_text, title or extracted_title)
            if not positioning and title:
                positioning = f"《{title}》看起来是一个项目工作台。"
        if signals["asks_summary"]:
            if not positioning:
                return DirectAnswerDecision(False, None, "positioning_not_reliable", 0.2, signals)
            answer = f"第一行标题：`# {title or extracted_title}`\n{positioning}"
            return DirectAnswerDecision(True, answer, "readme_title_and_positioning", 0.95 if title else 0.82, signals)
        answer = f"第一行标题：`# {title or extracted_title}`" if title else f"第一行：`{extracted_title}`"
        return DirectAnswerDecision(True, answer, "readme_title_only", 0.9 if title else 0.8, signals)

    if signals["asks_first_line"] and first_line:
        answer = f"第一行：`{first_line}`"
        return DirectAnswerDecision(True, answer, "file_first_line", 0.84, signals)

    if signals["asks_field"] and version:
        answer = f"版本号：`{version}`"
        return DirectAnswerDecision(True, answer, "version_extract", 0.82, signals)

    return DirectAnswerDecision(False, None, "no_supported_direct_answer_pattern", 0.2, signals)

"""Narrow read-task shortcut detection for classic executor bypass."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


READ_SHORTCUT_ENV_VAR = "GENERIC_AGENT_READ_SHORTCUT"

_VIEW_HINTS = (
    "看看",
    "查看",
    "读取",
    "打开",
    "显示",
    "提取",
    "抽取",
    "read",
    "show",
    "open",
    "view",
    "cat",
    "display",
)

_FIRST_LINE_HINTS = (
    "第一行",
    "标题",
    "title",
    "headline",
    "first line",
)

_SUMMARY_HINTS = (
    "一句话",
    "一句话总结",
    "项目定位",
    "summary",
    "定位",
)

_BANNED_ACTION_PHRASES = (
    "修改",
    "实现",
    "修复",
    "写入",
    "patch",
    "edit",
    "modify",
    "fix",
    "运行",
    "测试",
    "安装",
    "启动",
    "部署",
    "run",
    "test",
    "install",
    "start",
    "deploy",
)

_BANNED_COMPLEX_PHRASES = (
    "分析",
    "解释",
    "审查",
    "优化",
    "重构",
    "对比",
    "找问题",
    "执行流程",
    "代码结构",
    "架构",
    "逻辑",
    "review",
    "analyze",
    "analysis",
    "explain",
    "optimize",
    "refactor",
    "compare",
    "code structure",
    "execution flow",
    "architecture",
    "logic",
)

_README_CANDIDATES = ("README.md", "readme.md", "README.txt", "README")
_ALLOWED_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
_MAX_LINE_COUNT = 200


def read_shortcut_enabled() -> bool:
    return str(os.environ.get(READ_SHORTCUT_ENV_VAR, "")).strip() == "1"


@dataclass
class ReadShortcutDecision:
    should_shortcut: bool
    reason: str
    confidence: float
    target_file: str | None = None
    extraction_type: str | None = None
    line_count: int | None = None
    signals: dict[str, Any] = field(default_factory=dict)


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _resolve_project_root(project_root: str | Path | None) -> Path:
    return Path(project_root or Path.cwd()).resolve()


def _find_readme(project_root: Path) -> Path | None:
    for candidate in _README_CANDIDATES:
        path = (project_root / candidate).resolve()
        if path.is_file():
            return path
    return None


def _path_within_root(path: Path, project_root: Path) -> bool:
    try:
        path.relative_to(project_root)
        return True
    except ValueError:
        return False


def _extract_requested_line_count(user_input: str) -> int:
    text = str(user_input or "")
    for pattern in (
        r"前\s*(\d+)\s*行",
        r"first\s*(\d+)\s*lines?",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                continue
            return max(1, min(value, _MAX_LINE_COUNT))
    return 80


def _candidate_strings(text: str) -> list[str]:
    candidates: list[str] = []
    candidates.extend(re.findall(r"`([^`]+)`", text))
    candidates.extend(re.findall(r'"([^"]+)"', text))
    candidates.extend(re.findall(r"'([^']+)'", text))
    path_pattern = (
        r"(?<![\w.-])"
        r"([A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+\.(?:py|md|txt|json|yaml|yml|toml))"
        r"(?![\w.-])"
    )
    file_pattern = (
        r"(?<![\w.-])"
        r"([A-Za-z0-9_.-]+\.(?:py|md|txt|json|yaml|yml|toml))"
        r"(?![\w.-])"
    )
    candidates.extend(re.findall(path_pattern, text, flags=re.IGNORECASE))
    candidates.extend(re.findall(file_pattern, text, flags=re.IGNORECASE))
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        item = str(candidate or "").strip().strip("\"'")
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _is_absolute_candidate(candidate: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", candidate)) or candidate.startswith(("/", "\\"))


def _contains_parent_ref(candidate: str) -> bool:
    normalized = candidate.replace("\\", "/")
    return any(part == ".." for part in normalized.split("/"))


def _resolve_explicit_file_candidate(candidate: str, project_root: Path) -> tuple[Path | None, str]:
    raw = str(candidate or "").strip().strip("\"'")
    if not raw:
        return None, "empty_candidate"
    if _is_absolute_candidate(raw):
        return None, "absolute_path_not_allowed"
    if _contains_parent_ref(raw):
        return None, "path_traversal_not_allowed"

    normalized = raw.replace("\\", "/")
    relative_candidate = Path(normalized)
    suffix = relative_candidate.suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES and relative_candidate.name not in _README_CANDIDATES:
        return None, "unsupported_extension"

    if len(relative_candidate.parts) > 1:
        target = (project_root / relative_candidate).resolve()
        if not _path_within_root(target, project_root):
            return None, "path_outside_project_root"
        if not target.is_file():
            return None, "explicit_file_not_found"
        return target, "ok"

    direct_target = (project_root / relative_candidate.name).resolve()
    if direct_target.is_file() and _path_within_root(direct_target, project_root):
        return direct_target, "ok"

    matches = [
        path.resolve()
        for path in project_root.rglob(relative_candidate.name)
        if path.is_file() and _path_within_root(path.resolve(), project_root)
    ]
    if len(matches) == 1:
        return matches[0], "ok"
    if len(matches) > 1:
        return None, "ambiguous_filename"
    return None, "explicit_file_not_found"


def _resolve_explicit_file(user_input: str, project_root: Path) -> tuple[Path | None, str, str | None]:
    for candidate in _candidate_strings(str(user_input or "")):
        target, reason = _resolve_explicit_file_candidate(candidate, project_root)
        if target is not None:
            return target, "ok", candidate
        if reason in {"absolute_path_not_allowed", "path_traversal_not_allowed", "ambiguous_filename"}:
            return None, reason, candidate
    return None, "explicit_file_not_found", None


def detect_read_shortcut(user_input: str, project_root: str | Path | None = None) -> ReadShortcutDecision:
    root = _resolve_project_root(project_root)
    original = str(user_input or "")
    lowered = _normalize(original)
    signals: dict[str, Any] = {
        "project_root": str(root),
        "is_view_request": _contains_any(lowered, _VIEW_HINTS),
        "asks_first_line": _contains_any(lowered, _FIRST_LINE_HINTS),
        "asks_summary": _contains_any(lowered, _SUMMARY_HINTS),
        "mentions_readme": "readme" in lowered,
        "line_count": _extract_requested_line_count(original),
    }

    if not signals["is_view_request"]:
        return ReadShortcutDecision(False, "not_view_request", 0.0, signals=signals)
    if _contains_any(lowered, _BANNED_ACTION_PHRASES):
        return ReadShortcutDecision(False, "action_request_not_supported", 0.0, signals=signals)
    if _contains_any(lowered, _BANNED_COMPLEX_PHRASES):
        return ReadShortcutDecision(False, "analysis_or_modification_request_not_supported", 0.0, signals=signals)

    if signals["mentions_readme"] and (signals["asks_first_line"] or signals["asks_summary"]):
        target = _find_readme(root)
        signals["readme_found"] = bool(target)
        if target is None:
            return ReadShortcutDecision(False, "readme_not_found", 0.15, signals=signals)
        extraction_type = "readme_title_and_positioning" if signals["asks_summary"] else "readme_title"
        return ReadShortcutDecision(
            True,
            "readme_simple_extract",
            0.98 if signals["asks_summary"] else 0.95,
            target_file=str(target),
            extraction_type=extraction_type,
            line_count=50,
            signals=signals,
        )

    explicit_path, explicit_reason, explicit_candidate = _resolve_explicit_file(original, root)
    signals["explicit_path_found"] = bool(explicit_path)
    signals["explicit_candidate"] = explicit_candidate
    signals["explicit_reason"] = explicit_reason

    if explicit_reason == "absolute_path_not_allowed":
        return ReadShortcutDecision(False, "absolute_path_not_allowed", 0.0, signals=signals)
    if explicit_reason == "path_traversal_not_allowed":
        return ReadShortcutDecision(False, "path_traversal_not_allowed", 0.0, signals=signals)
    if explicit_reason == "ambiguous_filename":
        return ReadShortcutDecision(False, "ambiguous_filename", 0.1, signals=signals)
    if explicit_path is None:
        return ReadShortcutDecision(False, "explicit_file_not_found", 0.1, signals=signals)

    if signals["asks_summary"]:
        return ReadShortcutDecision(False, "explicit_file_summary_not_supported", 0.0, signals=signals)

    if signals["asks_first_line"]:
        return ReadShortcutDecision(
            True,
            "explicit_file_first_line",
            0.93,
            target_file=str(explicit_path),
            extraction_type="file_first_line",
            line_count=5,
            signals=signals,
        )

    line_count = int(signals["line_count"] or 80)
    return ReadShortcutDecision(
        True,
        "explicit_file_view",
        0.96 if line_count >= 20 else 0.92,
        target_file=str(explicit_path),
        extraction_type=f"explicit_file_view:{line_count}",
        line_count=line_count,
        signals=signals,
    )

"""Read-prefetch detector and safe file pre-loader for context injection.

Phase 1 (existing): detect analysis-oriented single-file prefetch candidates.
Phase 2 (added):  safe file content reading + context builder for injection.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

READ_PREFETCH_ENV_VAR = "GENERIC_AGENT_READ_PREFETCH"
_READ_PREFETCH_ENABLED_DEFAULT = False

_ALLOWED_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
_MAX_FILE_SIZE_BYTES = 512 * 1024  # 512KB — skip files larger than this

_SENSITIVE_PATH_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(^|[/\\])\.env(\..*)?$",
        r"(^|[/\\])mykey\.py$",
        r"(^|[/\\])mykey\.json$",
        r"(^|[/\\])credentials",
        r"(^|[/\\])secrets?[/\\]",
        r"(^|[/\\])\.git[/\\]",
        r"(^|[/\\])__pycache__[/\\]",
        r"(^|[/\\])\.claude[/\\]",
    )
]

_ANALYSIS_HINTS = (
    "分析",
    "解释",
    "梳理",
    "理解",
    "执行流程",
    "代码结构",
    "路由逻辑",
    "turn loop",
    "workflow",
)

_ACTION_BANS = (
    "修改",
    "修复",
    "实现",
    "重构",
    "优化",
    "删除",
    "写入",
    "patch",
    "运行",
    "测试",
    "部署",
    "安装",
    "modify",
    "fix",
    "implement",
    "refactor",
    "optimize",
    "delete",
    "write",
    "run",
    "test",
    "deploy",
    "install",
)


@dataclass
class ReadPrefetchDecision:
    should_prefetch: bool
    target_file: str | None
    reason: str
    confidence: float
    max_lines: int
    max_chars: int
    signals: list[str] = field(default_factory=list)


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _contains_any(text: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        if phrase.lower() in text:
            return phrase
    return None


def _resolve_project_root(project_root: str | Path) -> Path:
    return Path(project_root).resolve()


def _path_within_root(path: Path, project_root: Path) -> bool:
    try:
        path.relative_to(project_root)
        return True
    except ValueError:
        return False


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
    seen: set[str] = set()
    unique: list[str] = []
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
    if _is_absolute_candidate(raw) or _contains_parent_ref(raw):
        return None, "unsafe_path"

    normalized = raw.replace("\\", "/")
    relative_candidate = Path(normalized)
    if relative_candidate.suffix.lower() not in _ALLOWED_SUFFIXES:
        return None, "unsupported_extension"

    if len(relative_candidate.parts) > 1:
        target = (project_root / relative_candidate).resolve()
        if not _path_within_root(target, project_root):
            return None, "unsafe_path"
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


def _resolve_explicit_file(query: str, project_root: Path) -> tuple[Path | None, str, str | None]:
    candidates = _candidate_strings(query)
    if not candidates:
        return None, "no_explicit_file", None
    for candidate in candidates:
        target, reason = _resolve_explicit_file_candidate(candidate, project_root)
        if target is not None:
            return target, "ok", candidate
        if reason in {"unsafe_path", "ambiguous_filename"}:
            return None, reason, candidate
    return None, "explicit_file_not_found", candidates[0]


def _analysis_intent(query: str) -> tuple[bool, list[str]]:
    signals: list[str] = []
    matched = _contains_any(query, _ANALYSIS_HINTS)
    if matched:
        signals.append(f"analysis_intent:{matched}")
        return True, signals

    if "看看" in query and ("逻辑" in query or "执行流程" in query):
        signals.append("analysis_intent:看看...逻辑/执行流程")
        return True, signals

    return False, signals


def detect_read_prefetch(
    query: str,
    project_root: str | Path,
    default_max_lines: int = 200,
    default_max_chars: int = 12000,
) -> ReadPrefetchDecision:
    root = _resolve_project_root(project_root)
    normalized = _normalize(query)
    max_lines = max(1, int(default_max_lines or 200))
    max_chars = max(1, int(default_max_chars or 12000))
    signals: list[str] = [f"project_root:{root}"]

    banned = _contains_any(normalized, _ACTION_BANS)
    if banned:
        signals.append(f"blocked_action:{banned}")
        return ReadPrefetchDecision(False, None, "action_request_not_supported", 0.0, max_lines, max_chars, signals)

    has_analysis_intent, intent_signals = _analysis_intent(normalized)
    signals.extend(intent_signals)
    if not has_analysis_intent:
        return ReadPrefetchDecision(False, None, "not_analysis_request", 0.0, max_lines, max_chars, signals)

    target, reason, candidate = _resolve_explicit_file(str(query or ""), root)
    if candidate:
        signals.append(f"file_candidate:{candidate}")

    if reason == "unsafe_path":
        signals.append("unsafe_path")
        return ReadPrefetchDecision(False, None, "unsafe_path", 0.0, max_lines, max_chars, signals)
    if reason == "ambiguous_filename":
        signals.append("ambiguous_filename")
        return ReadPrefetchDecision(False, None, "ambiguous_filename", 0.1, max_lines, max_chars, signals)
    if target is None:
        signals.append(reason)
        return ReadPrefetchDecision(False, None, reason, 0.0, max_lines, max_chars, signals)

    relative_target = target.relative_to(root).as_posix()
    signals.append(f"target_file:{relative_target}")
    return ReadPrefetchDecision(
        True,
        target_file=relative_target,
        reason="analysis_single_file_prefetch_candidate",
        confidence=0.88,
        max_lines=max_lines,
        max_chars=max_chars,
        signals=signals,
    )


# ── Phase 2: safe file reading + context builder ──────────────────


def is_read_prefetch_enabled() -> bool:
    return os.environ.get(READ_PREFETCH_ENV_VAR, "").strip() == "1"


def _is_sensitive_path(target: str | Path) -> bool:
    path_str = str(target).replace("\\", "/")
    for pattern in _SENSITIVE_PATH_PATTERNS:
        if pattern.search(path_str):
            return True
    return False


def _is_binary_content(first_bytes: bytes) -> bool:
    """Check for null bytes or high ratio of non-printable characters.
    UTF-8 multi-byte sequences are treated as text if they decode cleanly.
    """
    if b"\x00" in first_bytes:
        return True
    # Try UTF-8 decode — if it succeeds, treat as text (covers CJK, emoji, etc.)
    try:
        first_bytes.decode("utf-8")
        return False
    except UnicodeDecodeError:
        pass
    text_chars = sum(1 for b in first_bytes if 32 <= b < 127 or b in (9, 10, 13))
    return (text_chars / max(len(first_bytes), 1)) < 0.85


def safe_read_prefetch_content(
    target_file: str,
    project_root: str | Path,
    max_lines: int = 200,
    max_chars: int = 12000,
) -> tuple[str | None, str, dict]:
    """Safely read file content for prefetch injection.

    Returns (content, reason, metadata).
    content is None if the file should not be injected.
    """
    metadata: dict = {"target": target_file}

    root = Path(project_root).resolve()
    target_path = (root / target_file).resolve()

    # Safety gate 1: path containment
    try:
        target_path.relative_to(root)
    except ValueError:
        return None, "path_escape", {**metadata, "reason": "path not within project root"}

    # Safety gate 2: sensitive path
    if _is_sensitive_path(target_file):
        return None, "sensitive_path", {**metadata, "reason": "sensitive file path"}

    # Safety gate 3: file existence
    if not target_path.is_file():
        return None, "file_not_found", {**metadata, "reason": "file does not exist"}

    # Safety gate 4: file size
    file_size = target_path.stat().st_size
    metadata["file_size"] = file_size
    if file_size > _MAX_FILE_SIZE_BYTES:
        return None, "file_too_large", {**metadata, "reason": f"file size {file_size} > {_MAX_FILE_SIZE_BYTES}"}

    # Safety gate 5: binary check (first 4KB)
    try:
        with open(target_path, "rb") as fh:
            head = fh.read(4096)
    except Exception:
        return None, "read_error", {**metadata, "reason": "could not open file"}

    if _is_binary_content(head):
        return None, "binary_content", {**metadata, "reason": "binary file detected"}

    # Safe read: decode as UTF-8, apply line/char limits
    try:
        raw = head.decode("utf-8", errors="replace")
    except Exception:
        return None, "decode_error", {**metadata, "reason": "utf-8 decode failed"}

    lines = raw.split("\n")
    total_lines = len(lines)
    metadata["total_lines"] = total_lines

    truncated = total_lines > max_lines
    if truncated:
        lines = lines[:max_lines]

    text = "\n".join(lines)
    total_chars = len(text)
    metadata["total_chars"] = total_chars

    if total_chars > max_chars:
        text = text[:max_chars]
        truncated = True

    metadata["truncated"] = truncated
    metadata["injected_lines"] = len(lines) if not truncated else min(len(lines), max_lines)
    metadata["injected_chars"] = len(text)

    return text, "ok", metadata


def build_read_prefetch_context(
    content: str,
    target_file: str,
    reason: str,
    confidence: float,
    truncated: bool,
) -> str:
    """Format read_prefetch content as a clearly-bounded user context block."""
    header = (
        f"### [READ PREFETCH CONTEXT]\n"
        f"source_file: {target_file}\n"
        f"reason: {reason}\n"
        f"confidence: {confidence:.2f}\n"
    )
    if truncated:
        header += "truncated: true (file exceeded line/char limit)\n"
    return f"{header}\nexcerpt:\n```\n{content}\n```"

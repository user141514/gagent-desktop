from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


TOOL_PATH_GUARD_ENV_VAR = "GENERIC_AGENT_TOOL_PATH_GUARD"
TOOL_PATH_ALLOW_SENSITIVE_ENV_VAR = "GENERIC_AGENT_TOOL_PATH_ALLOW_SENSITIVE"

_DISABLED_VALUES = {"0", "false", "no", "off"}
_SENSITIVE_PATTERNS = (
    r"(^|[/\\])\.env(\..*)?$",
    r"(^|[/\\])mykey\.py$",
    r"(^|[/\\])mykey\.json$",
    r"(^|[/\\])secrets?([/\\]|$)",
    r"(^|[/\\])credentials?(\.[^/\\]+)?$",
    r"(^|[/\\])token(\.[^/\\]+)?$",
    r"(^|[/\\])\.git[/\\]config$",
    r"(^|[/\\])\.ssh([/\\]|$)",
)


@dataclass(frozen=True)
class ToolPathResult:
    allowed: bool
    path: str
    reason: str
    message: str
    mode: str = "read"

    def to_error_dict(self) -> dict[str, str]:
        return {
            "status": "error",
            "reason": self.reason,
            "msg": self.message,
            "path": self.path,
        }


def tool_path_guard_enabled() -> bool:
    return os.environ.get(TOOL_PATH_GUARD_ENV_VAR, "1").strip().lower() not in _DISABLED_VALUES


def resolve_tool_path(
    path: str,
    *,
    base_dir: str | Path,
    project_root: str | Path,
    mode: str = "read",
) -> ToolPathResult:
    raw = str(path or "").strip().strip("\"'")
    if not raw:
        return ToolPathResult(False, "", "empty_path", "Tool path is empty.", mode=mode)

    base = Path(base_dir).resolve()
    root = Path(project_root).resolve()
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
    resolved_text = str(resolved)

    if not tool_path_guard_enabled():
        return ToolPathResult(True, resolved_text, "disabled", "Tool path guard disabled.", mode=mode)

    if not _path_within_root(resolved, root):
        return ToolPathResult(
            False,
            resolved_text,
            "path_escape",
            f"Refusing {mode} outside project root: {resolved_text}",
            mode=mode,
        )

    if _is_sensitive_path(resolved) and not _allow_sensitive_paths():
        return ToolPathResult(
            False,
            resolved_text,
            "sensitive_path",
            f"Refusing {mode} of sensitive path: {resolved_text}",
            mode=mode,
        )

    return ToolPathResult(True, resolved_text, "ok", "Path allowed.", mode=mode)


def _path_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_sensitive_path(path: Path | str) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in _SENSITIVE_PATTERNS)


def _allow_sensitive_paths() -> bool:
    return os.environ.get(TOOL_PATH_ALLOW_SENSITIVE_ENV_VAR, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


__all__ = [
    "TOOL_PATH_ALLOW_SENSITIVE_ENV_VAR",
    "TOOL_PATH_GUARD_ENV_VAR",
    "ToolPathResult",
    "resolve_tool_path",
    "tool_path_guard_enabled",
]

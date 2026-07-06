from __future__ import annotations

from pathlib import Path


DEFAULT_MAX_CHARS = 2500
TRUNCATION_MARKER = "\n\n[truncated]"


def _truncate_text(text: str, max_chars: int) -> str:
    limit = max(int(max_chars or 0), 1)
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATION_MARKER):
        return text[:limit]
    keep = limit - len(TRUNCATION_MARKER)
    return text[:keep].rstrip() + TRUNCATION_MARKER


def load_skill_markdown(file_path: str | Path, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    path = Path(file_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return _truncate_text(text, max_chars=max_chars)

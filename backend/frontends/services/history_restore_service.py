"""History restore service — decouples history file discovery/parsing from Streamlit UI.

Receives file paths and backend kind, delegates to ``chatapp_common.py`` for
the actual ``format_restore`` / ``unpack_restore_result`` parsing, and returns
plain dataclass results.  Does NOT depend on Streamlit, ``st.session_state``,
or agent objects.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class HistoryFileInfo:
    """Metadata for a single history file.  Streamlit-free."""

    filepath: str
    filename: str
    mtime: float = 0.0
    mtime_str: str = ""
    size_kb: int = 0
    title: str = ""


@dataclass
class RestoredConversation:
    """Result of restoring a conversation from a history file.

    ``restored`` is the raw data: a list of input_items (new format)
    or a list of lines (old format).  ``fmt_type`` is ``"input_items"``
    or ``"lines"``.
    """

    restored: list[Any] = field(default_factory=list)
    count: int = 0
    fmt_type: str = "lines"
    filename: str = ""


class HistoryRestoreService:
    """Stateless service for history file operations.

    No Streamlit, no ``st.session_state``, no agent mutations.
    All heavy parsing delegates to ``chatapp_common`` helpers.
    """

    _SYNTHETIC_TITLE_PREFIXES = (
        "[LEGACY PROJECT MEMORY",
        "[RECENT CONVERSATION",
        "[ROUTER_HINT]",
        "### [WORKING MEMORY]",
        "### Answer Quality",
        "### Problem Framing",
        "### Research and Code Priority Guard",
        "[RESEARCH WORKFLOW]",
        "You are the execution engine",
        "[DANGER]",
        "[REFLECT]",
        "[System]",
        "TOOL_EVENTS:",
        "cwd =",
    )

    # ── file discovery ──────────────────────────────────────────────────

    def __init__(self, project_root: str | None = None) -> None:
        self.project_root = os.path.abspath(project_root) if project_root else ""

    def _history_dir(self, backend_kind: str = "") -> str:
        subdir = "model_responses_openai" if backend_kind == "openai-agents" else "model_responses"
        if self.project_root:
            return os.path.join(self.project_root, "temp", subdir)
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(script_dir, "..", "temp", subdir)

    def list_files(self, backend_kind: str = "") -> list[HistoryFileInfo]:
        """List available history files, newest first."""
        hist_dir = self._history_dir(backend_kind)
        if not os.path.exists(hist_dir):
            return []
        files = glob.glob(os.path.join(hist_dir, "model_responses_*.txt"))
        files.sort(key=os.path.getmtime, reverse=True)
        results: list[HistoryFileInfo] = []
        for filepath in files[:20]:
            fname = os.path.basename(filepath)
            mtime = os.path.getmtime(filepath)
            size_kb = max(1, os.path.getsize(filepath) // 1024)
            info = HistoryFileInfo(
                filepath=filepath,
                filename=fname,
                mtime=mtime,
                mtime_str=datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M"),
                size_kb=size_kb,
            )
            results.append(info)
        return results

    # ── preview ─────────────────────────────────────────────────────────

    @staticmethod
    def preview(filepath: str, max_lines: int = 30) -> str:
        """Read the first *max_lines* lines of a history file."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return "\n".join(f.read().splitlines()[:max_lines])
        except Exception as e:
            return f"预览失败: {e}"

    # ── title extraction ────────────────────────────────────────────────

    def extract_title(self, filepath: str, backend_kind: str = "") -> str:
        """Extract the first real user question from a history file for display."""
        from frontends.chatapp_common import format_restore, _content_to_text, unpack_restore_result

        result, err = format_restore(filepath, backend_kind=backend_kind)
        if err or not result:
            return ""
        restored, _, _, fmt_type = unpack_restore_result(result)
        questions: list[str] = []
        if fmt_type == "input_items":
            for item in restored or []:
                if not isinstance(item, dict) or item.get("role") != "user":
                    continue
                text = _content_to_text(item.get("content", ""))
                title = self._title_from_user_text(text)
                if title:
                    return self._truncate_title(title)
        else:
            questions = [
                line[8:] for line in restored
                if isinstance(line, str) and line.startswith("[USER]: ")
            ]
        for question in questions:
            title = self._title_from_user_text(question)
            if title:
                return self._truncate_title(title)
        first_q = self._extract_first_user_question(filepath)
        if first_q:
            return self._truncate_title(first_q)
        return ""

    @classmethod
    def _looks_like_synthetic_user_text(cls, text: str) -> bool:
        stripped = (text or "").lstrip()
        if "<history>" in stripped:
            return True
        return any(stripped.startswith(prefix) for prefix in cls._SYNTHETIC_TITLE_PREFIXES)

    @staticmethod
    def _first_nonempty_line(text: str) -> str:
        for line in (text or "").splitlines():
            line = line.strip()
            if line:
                return line
        return ""

    @classmethod
    def _title_from_user_text(cls, text: str) -> str:
        from frontends.chatapp_common import FILE_HINT, _recent_conversation_lines

        stripped = (text or "").strip()
        if stripped.startswith(FILE_HINT):
            stripped = stripped[len(FILE_HINT):].lstrip()
        recent_lines = _recent_conversation_lines(stripped)
        for line in recent_lines:
            if line.startswith("[USER]: "):
                candidate = line[8:].strip()
                if candidate and not cls._looks_like_synthetic_user_text(candidate):
                    return candidate.replace("\n", " ").strip()
        for marker in ("### 用户当前消息", "### Current User Message", "Original user request:"):
            if marker in stripped:
                candidate = stripped.split(marker, 1)[-1].strip()
                return cls._first_nonempty_line(candidate).replace("\n", " ").strip()
        if cls._looks_like_synthetic_user_text(stripped):
            return ""
        return stripped.replace("\n", " ").strip()

    @staticmethod
    def _truncate_title(title: str) -> str:
        title = (title or "").replace("\n", " ").strip()
        return title[:42] + ("..." if len(title) > 42 else "")

    @staticmethod
    def _extract_first_user_question(filepath: str) -> str:
        """Read the first Prompt block and extract the original user question,
        bypassing system-injected context like multi-agent handoff prompts."""
        from frontends.chatapp_common import (
            RESTORE_BLOCK_RE,
            _native_prompt_obj,
            _native_prompt_text,
        )
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return ""
        for label, body in RESTORE_BLOCK_RE.findall(content):
            if label != "Prompt":
                continue
            prompt = _native_prompt_obj(body)
            if prompt is None:
                continue
            text = _native_prompt_text(prompt)
            # 标准标记：### 用户当前消息 / ### Current User Message
            user = HistoryRestoreService._title_from_user_text(text)
            if user:
                return user.replace("\n", " ").strip()
            # 多智能体标记：Original user request:
            if "Original user request:" in text:
                after = text.split("Original user request:", 1)[-1]
                first_line = after.strip().split("\n")[0].strip()
                if first_line and not first_line.startswith("Execution plan"):
                    return first_line.replace("\n", " ").strip()
        return ""

    # ── restore ─────────────────────────────────────────────────────────

    def restore(
        self, filepath: str, backend_kind: str = ""
    ) -> RestoredConversation | None:
        """Parse a history file and return a ``RestoredConversation``.

        Returns None if the file cannot be parsed.
        The caller (stapp.py) is responsible for injecting the result into
        ``st.session_state.messages`` and ``agent.history``.
        """
        from frontends.chatapp_common import format_restore, unpack_restore_result

        result, err = format_restore(filepath, backend_kind=backend_kind)
        if err or not result:
            return None
        restored, _, count, fmt_type = unpack_restore_result(result)
        return RestoredConversation(
            restored=restored or [],
            count=count,
            fmt_type=fmt_type or "lines",
            filename=os.path.basename(filepath),
        )

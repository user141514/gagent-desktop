"""Agent output formatter — decouples display formatting from the agent loop.

Extracted from ``core/agent_loop.py``: ``_clean_content``, ``_compact_tool_args``,
and the verbose/non-verbose display logic are now encapsulated here.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod


_SHOW_TOOL_CALLS = os.environ.get("GENERIC_AGENT_SHOW_TOOL_CALLS", "").strip().lower() in (
    "1", "true", "yes", "on",
)


class AgentOutputFormatter(ABC):
    """Abstract formatter that controls how agent output is presented.

    The agent loop yields raw text. Formatters decorate it with
    turn markers, tool-call formatting, etc. for different frontends.
    """

    @abstractmethod
    def format_turn_start(self, turn: int) -> str:
        """Text emitted when a new LLM turn begins."""
        ...

    @abstractmethod
    def format_turn_end(self, turn: int) -> str:
        """Text emitted when an LLM turn completes."""
        ...

    @abstractmethod
    def format_tool_call(self, tool_name: str, arguments: dict | str) -> str:
        """Text emitted when the agent invokes a tool."""
        ...

    @abstractmethod
    def format_tool_result(self, tool_name: str, result_summary: str) -> str:
        """Text emitted when a tool returns a result."""
        ...

    @abstractmethod
    def format_error(self, error_message: str) -> str:
        """Text emitted on error."""
        ...

    @abstractmethod
    def clean_content(self, text: str) -> str:
        """Clean LLM response content for display (shrink code, strip tags)."""
        ...

    @abstractmethod
    def compact_tool_args(self, tool_name: str, args: dict) -> str:
        """Compact tool arguments into a short display string."""
        ...

    @abstractmethod
    def is_verbose(self) -> bool:
        """Whether this formatter produces verbose (markdown) output."""
        ...

    def hide_tool_calls(self) -> bool:
        """Whether tool-call and tool-result output should be suppressed.

        Tool calls are hidden by default.  Set
        ``GENERIC_AGENT_SHOW_TOOL_CALLS=1`` to restore the old behaviour
        where every ``file_read(…)`` / ``code_run(…)`` invocation is
        printed inline.
        """
        return not _SHOW_TOOL_CALLS


class NullFormatter(AgentOutputFormatter):
    """Minimal formatter — emits nothing extra. Raw text only."""

    def format_turn_start(self, turn: int) -> str:
        return ""

    def format_turn_end(self, turn: int) -> str:
        return ""

    def format_tool_call(self, tool_name: str, arguments: dict | str) -> str:
        return ""

    def format_tool_result(self, tool_name: str, result_summary: str) -> str:
        return ""

    def format_error(self, error_message: str) -> str:
        return ""

    def clean_content(self, text: str) -> str:
        return CompactFormatter._clean_content_static(text)

    def compact_tool_args(self, tool_name: str, args: dict) -> str:
        return CompactFormatter._compact_tool_args_static(tool_name, args)

    def is_verbose(self) -> bool:
        return False


class CompactFormatter(AgentOutputFormatter):
    """Compact formatter — non-verbose mode: ``tool_name(args)`` inline.

    Equivalent to the old ``verbose=False`` behavior in agent_loop.py.
    """

    def format_turn_start(self, turn: int) -> str:
        return ""

    def format_turn_end(self, turn: int) -> str:
        return ""

    def format_tool_call(self, tool_name: str, arguments: dict | str) -> str:
        if self.hide_tool_calls():
            return ""
        if isinstance(arguments, str):
            return f"{tool_name}({arguments[:120]})\n\n\n"
        return f"{tool_name}({self._compact_tool_args_static(tool_name, arguments)})\n\n\n"

    def format_tool_result(self, tool_name: str, result_summary: str) -> str:
        return ""

    def format_error(self, error_message: str) -> str:
        return ""

    def clean_content(self, text: str) -> str:
        return self._clean_content_static(text)

    def compact_tool_args(self, tool_name: str, args: dict) -> str:
        return self._compact_tool_args_static(tool_name, args)

    def is_verbose(self) -> bool:
        return False

    # ── static helpers (moved from agent_loop.py) ───────────────────────

    @staticmethod
    def _clean_content_static(text: str) -> str:
        """Shrink oversized code blocks, strip verbose XML tags, collapse blank lines."""
        if not text:
            return ""

        def _shrink_code(m):
            lines = m.group(0).split("\n")
            lang = lines[0].replace("```", "").strip()
            body = [l for l in lines[1:-1] if l.strip()]
            if len(body) <= 6:
                return m.group(0)
            preview = "\n".join(body[:5])
            return f"```{lang}\n{preview}\n  ... ({len(body)} lines)\n```"

        text = re.sub(r"```[\s\S]*?```", _shrink_code, text)
        for p in [
            r"<file_content>[\s\S]*?</file_content>",
            r"<tool_(?:use|call)>[\s\S]*?</tool_(?:use|call)>",
            r"(\r?\n){3,}",
        ]:
            text = re.sub(p, "\n\n" if "\\n" in p else "", text)
        return text.strip()

    @staticmethod
    def _compact_tool_args_static(name: str, args: dict) -> str:
        """Compact tool args into a short display string (< 120 chars)."""
        a = {k: v for k, v in args.items() if k != "_index"}
        for k in ("path",):
            if k in a:
                a[k] = os.path.basename(a[k])
        if name == "update_working_checkpoint":
            s = a.get("key_info", "")
            return (s[:60] + "...") if len(s) > 60 else s
        s = json.dumps(a, ensure_ascii=False)
        return (s[:120] + "...") if len(s) > 120 else s


class VerboseFormatter(AgentOutputFormatter):
    """Markdown-rich formatter — equivalent to old ``verbose=True`` mode.

    Emits ``**LLM Running (Turn N)...**`` markers, tool call blocks,
    and ``[Error]`` formatting.
    """

    def format_turn_start(self, turn: int) -> str:
        return f"\n**LLM Running (Turn {turn}) ...**\n"

    def format_turn_end(self, turn: int) -> str:
        return ""

    def format_tool_call(self, tool_name: str, arguments: dict | str) -> str:
        if self.hide_tool_calls():
            return ""
        if isinstance(arguments, dict):
            args_str = json.dumps(arguments, ensure_ascii=False)
        else:
            args_str = str(arguments)
        return f"Tool: `{tool_name}` args:\n````text\n{args_str}\n````\n"

    def format_tool_result(self, tool_name: str, result_summary: str) -> str:
        if not result_summary:
            return ""
        preview = result_summary[:200].replace("\n", " ")
        return f"  → {preview}\n"

    def format_error(self, error_message: str) -> str:
        return f"\n```\n[Error] {error_message}\n```\n"

    def clean_content(self, text: str) -> str:
        return CompactFormatter._clean_content_static(text)

    def compact_tool_args(self, tool_name: str, args: dict) -> str:
        return CompactFormatter._compact_tool_args_static(tool_name, args)

    def is_verbose(self) -> bool:
        return True

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _format_args(args: dict | str) -> str:
        if isinstance(args, str):
            return args
        try:
            items = list(args.items())[:2]
            parts = [f"{k}={repr(v)[:60]}" for k, v in items]
            if len(args) > 2:
                parts.append("...")
            return ", ".join(parts)
        except Exception:
            return str(args)[:100]

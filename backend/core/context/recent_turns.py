"""
Recent Turns — lightweight short-term conversation context for model injection.

Does NOT maintain a persistent buffer. Reads from the existing input_items
list (OpenAI chat format) to build a condensed recent-conversation block.

Gated by GENERIC_AGENT_RECENT_TURNS env var (default: "1", enabled).
Set to "0" to disable injection entirely.
"""

from __future__ import annotations

import os
from typing import Any


# ── Ambiguous follow-up detection ────────────────────────────────────

_AMBIGUOUS_FOLLOWUP_PATTERNS = [
    # Pure dots / ellipsis
    lambda t: all(c in "." for c in t.strip()),
    # Zero-length or whitespace-only
    lambda t: not t.strip(),
    # Chinese anaphora — references that require prior context
    lambda t: t.strip() in {
        "继续", "继续。", "继续吧", "继续啊",
        "刚才那个", "刚才的", "那个", "上一个",
        "怎么改回去", "怎么改回来", "改回去", "改回来", "撤销",
        "按你说的做", "照你说的做", "就按你说的", "按你说的来",
        "然后呢", "然后", "还有呢", "还有吗",
        "为什么", "为啥", "什么意思", "怎么说",
        "详细说说", "详细说", "说详细点", "展开", "展开说说", "具体说说",
        "举个例子", "举例", "比如",
        "不对", "不是这样", "不对吧", "不対",
        "确定吗", "真的吗", "你确定",
        "重来", "重新来", "再来一次",
        "算了", "不管了",
        "嗯", "哦", "好", "好的", "行", "可以", "OK", "ok", "okay",
        "明白了", "懂了", "知道了",
        "接着说", "继续讲", "往下说",
    },
    # English anaphora
    lambda t: t.strip().lower() in {
        "continue", "go on", "keep going", "proceed",
        "that one", "the last one", "the previous one",
        "undo", "revert", "rollback", "change it back",
        "do what you said", "as you said", "per your suggestion",
        "and then", "what else", "anything else",
        "why", "what do you mean", "explain",
        "elaborate", "go into detail", "more details",
        "give an example", "for example",
        "wrong", "not correct", "that's wrong",
        "are you sure", "really",
        "start over", "redo", "retry",
        "nevermind", "forget it",
        "uh", "hmm", "ok", "okay", "got it", "understood",
        "go on", "next",
    },
    # Very short non-command messages (<=3 chars)
    lambda t: len(t.strip()) <= 3 and not any(
        kw in t.strip().lower() for kw in ("/", "?", "！", "!")
    ),
]


def is_ambiguous_followup(text: str) -> bool:
    """Return True if the user message likely refers to prior conversation.

    Detects anaphora ("...", "继续", "刚才那个"), back-references
    ("怎么改回去", "按你说的做"), and extremely short inputs that are
    not standalone commands.
    """
    for pattern in _AMBIGUOUS_FOLLOWUP_PATTERNS:
        try:
            if pattern(text):
                return True
        except Exception:
            continue
    return False


# ── Content extraction helpers ───────────────────────────────────────

def _extract_text(content: Any) -> str:
    """Extract plain text from an input_item content field.

    Handles both string content and list-of-blocks content (OpenAI format).
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            if part.get("type") in {"text", "input_text", "output_text"}:
                parts.append(str(part.get("text") or ""))
            elif part.get("type") == "refusal":
                parts.append(str(part.get("refusal") or ""))
    return "\n".join(p for p in parts if p)


def _summarize(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, adding ellipsis if needed."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


# ── Block builder ────────────────────────────────────────────────────

def build_recent_conversation_block(
    input_items: list[dict[str, Any]] | None,
    max_turns: int = 5,
    max_chars: int = 6000,
) -> str:
    """Build a condensed recent-conversation block from input_items.

    input_items is the OpenAI-format conversation list (role + content dicts).
    Returns a formatted string for injection into the model's user messages,
    or empty string if there is no conversation to summarize.

    The block format:

        [RECENT CONVERSATION — last N turns]
        USER: <original text>
        ASSISTANT: <response text>
        TOOL_EVENTS:
        - tool_name: args_summary → result_summary

        USER: <original text>
        ASSISTANT: <response text>
        TOOL_EVENTS:
        - none
        [/RECENT CONVERSATION]
    """
    if not input_items:
        return ""

    # ── Phase 1: extract raw turns ──
    raw_turns: list[dict[str, Any]] = []
    current: dict[str, Any] = {"user_texts": [], "assistant_texts": [], "tool_events": []}

    for item in input_items:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content_text = _extract_text(item.get("content"))

        if role == "user":
            # Skip internal execution-engine prompts (not real user messages)
            if content_text.startswith("You are the execution engine"):
                continue
            # Start a new turn when we see a user message
            # (but only if current turn has content)
            if current["user_texts"] or current["assistant_texts"] or current["tool_events"]:
                raw_turns.append(current)
                current = {"user_texts": [], "assistant_texts": [], "tool_events": []}
            if content_text.strip():
                current["user_texts"].append(content_text.strip())

        elif role == "assistant":
            if content_text.strip():
                current["assistant_texts"].append(content_text.strip())
            # Tool calls initiated by assistant
            for tc in item.get("tool_calls") or []:
                fn = tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)
                if fn:
                    name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", "unknown")
                    args = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", "")
                else:
                    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "unknown")
                    args = ""
                current["tool_events"].append({
                    "name": str(name or "unknown"),
                    "args": str(args or ""),
                    "result": None,
                    "status": "called",
                })

        elif role == "tool":
            # Tool result — attach to the most recent tool event with same name
            tool_name = str(item.get("name") or "unknown")
            result_text = _summarize(content_text, 300)
            # Try to match with a pending tool event
            matched = False
            for te in reversed(current["tool_events"]):
                if te["name"] == tool_name and te["result"] is None:
                    te["result"] = result_text
                    te["status"] = "done"
                    matched = True
                    break
            if not matched:
                current["tool_events"].append({
                    "name": tool_name,
                    "args": "",
                    "result": result_text,
                    "status": "result_only",
                })

    # Don't forget the last turn
    if current["user_texts"] or current["assistant_texts"] or current["tool_events"]:
        raw_turns.append(current)

    if not raw_turns:
        return ""

    # ── Phase 2: take last N turns ──
    recent = raw_turns[-max_turns:]

    # ── Phase 3: build formatted block ──
    header = f"[RECENT CONVERSATION — last {len(recent)} turns]"
    parts: list[str] = [header]
    total = len(header)

    for i, turn in enumerate(reversed(recent)):
        turn_num = len(recent) - i
        block_lines: list[str] = [f"## Turn {turn_num}"]

        # User text
        user_combined = "\n".join(turn["user_texts"]).strip()
        if user_combined:
            block_lines.append(f"USER: {user_combined}")

        # Assistant text
        assistant_combined = "\n".join(turn["assistant_texts"]).strip()
        if assistant_combined:
            block_lines.append(f"ASSISTANT: {assistant_combined}")

        # Tool events
        tool_events = turn["tool_events"]
        if tool_events:
            block_lines.append("TOOL_EVENTS:")
            for te in tool_events:
                line = f"- {te['name']}"
                if te.get("args") and te["args"].strip() and te["args"] != "{}":
                    args_short = _summarize(te["args"].strip(), 120)
                    line += f"({args_short})"
                if te.get("result"):
                    line += f" → {te['result']}"
                if te.get("status") == "called":
                    line += " [called — result not yet recorded]"
                block_lines.append(line)
        else:
            block_lines.append("TOOL_EVENTS:")
            block_lines.append("- none")

        block_lines.append("")  # blank line between turns
        block = "\n".join(block_lines)

        # Check budget
        if total + len(block) > max_chars:
            remaining = max_chars - total - 80
            if remaining > 100:
                truncated = block[:remaining] + "…\n"
                parts.append(truncated)
            parts.append(f"[… {len(recent) - i} earlier turns truncated …]")
            break

        parts.append(block)
        total += len(block)

    parts.append("[/RECENT CONVERSATION]")
    return "\n".join(parts)


# ── Clarification note for empty context ─────────────────────────────

def build_clarification_request() -> str:
    """Return a note asking the model to make assumptions and proceed.

    Used when the user sends an ambiguous follow-up but there is no
    recent conversation block to provide context.
    The model should make minimal, reversible assumptions rather than
    interrogating the user.
    """
    return (
        "[CONTEXT NOTE] The user sent an ambiguous message (e.g. '...', '继续', '怎么改回去') "
        "but there is NO recent conversation context available. "
        "Do NOT ask the user to clarify. Instead, make minimal, reversible "
        "assumptions based on what is observable (project state, recent git "
        "history, file structure, working directory) and proceed. "
        "State your assumptions briefly in <thinking>, then act. "
        "If the direction is wrong, the user will correct you."
    )


# ── Env-var gate ─────────────────────────────────────────────────────

def recent_turns_enabled() -> bool:
    """Master kill-switch. Returns True unless GENERIC_AGENT_RECENT_TURNS=0."""
    return os.environ.get("GENERIC_AGENT_RECENT_TURNS", "1") != "0"

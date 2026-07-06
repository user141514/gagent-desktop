"""Pure message conversion utilities -- history lines, chat messages, Claude API format."""
from __future__ import annotations

import json
import re
from typing import Any

_TURN_MARKER_RE = re.compile(r"\**LLM Running \(Turn (\d+)\) \.\.\.\**")
_INTERNAL_TAG_RE = re.compile(
    r"<\s*(?:thinking|summary|tool_use|tool_result|tool_call)\b[^>]*>"
    r"[\s\S]*?"
    r"<\s*/\s*(?:thinking|summary|tool_use|tool_result|tool_call)\s*>\s*",
    re.IGNORECASE,
)
_TOOL_BLOCK_RE = re.compile(
    r"^Tool:\s*`[^`]+`\s+args:\s*\n`{3,}[^\n]*\n[\s\S]*?\n`{3,}\s*",
    re.MULTILINE,
)
_FENCED_STATUS_RE = re.compile(
    r"^`{3,}\s*\n\[(?:Action|Status|Stdout|Stderr|Error|Path Guard|Info)\][\s\S]*?\n`{3,}\s*",
    re.MULTILINE,
)
_STATUS_LINE_RE = re.compile(
    r"^\[(?:Action|Status|Stdout|Stderr|Error|Path Guard|Info)\].*$",
    re.MULTILINE,
)
_TOOL_OR_JSON_LINE_RE = re.compile(
    r"^\s*(?:[a-z][a-z0-9_]*\(\{.*\}\)|"
    r"(?:\[\s*)?\{.*['\"]type['\"]\s*:\s*['\"](?:thinking|tool_use|tool_call)['\"].*\}\s*(?:\])?)\s*$",
    re.IGNORECASE,
)


def _restored_lines_to_inputs(restored: list[str]) -> list[dict[str, str]]:
    inputs: list[dict[str, str]] = []
    for line in restored:
        if line.startswith("[USER]: "):
            inputs.append({"role": "user", "content": line[8:]})
        elif line.startswith("[Agent] "):
            inputs.append({"role": "assistant", "content": line[8:]})
    return inputs


def extract_user_visible_text(text: str, latest_turn: int = 0) -> str:
    """Return text safe to show as the final assistant answer.

    Runtime trace markers, thinking/summary blocks, and tool transcripts are
    still preserved by structured trace events; they should not become the
    user-visible final answer.
    """
    value = str(text or "")
    markers = list(_TURN_MARKER_RE.finditer(value))
    if markers:
        marker = markers[-1]
        try:
            marker_turn = int(marker.group(1) or 0)
        except (TypeError, ValueError):
            marker_turn = 0
        if latest_turn <= 0 or marker_turn >= latest_turn:
            value = value[marker.end() :]
        else:
            value = ""

    value = _INTERNAL_TAG_RE.sub("", value)
    value = _TOOL_BLOCK_RE.sub("", value)
    value = _FENCED_STATUS_RE.sub("", value)
    value = _STATUS_LINE_RE.sub("", value)
    value = _TURN_MARKER_RE.sub("", value)

    visible_lines: list[str] = []
    for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _TOOL_OR_JSON_LINE_RE.match(line.strip()):
            continue
        visible_lines.append(line)
    value = "\n".join(visible_lines)
    value = re.sub(r"^\s*---+\s*", "", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _input_items_to_history_lines(input_items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in input_items or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _tool_message_content_to_text(item.get("content"))
        if not text and "output" in item:
            text = _tool_message_content_to_text(item.get("output"))
        text = (text or "").strip()
        if not text:
            continue
        prefix = "[USER]: " if role == "user" else "[Agent] "
        line = prefix + text
        if lines:
            same_role = (role == "user" and lines[-1].startswith("[USER]: ")) or (
                role == "assistant" and lines[-1].startswith("[Agent] ")
            )
            if same_role:
                lines[-1] += "\n\n" + text
                continue
        lines.append(line)
    return lines


def _message_content_to_claude_blocks(content: Any) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return [{"type": "text", "text": str(content)}]

    blocks: list[dict[str, Any]] = []
    for part in content:
        if isinstance(part, str):
            blocks.append({"type": "text", "text": part})
            continue
        if not isinstance(part, dict):
            blocks.append({"type": "text", "text": str(part)})
            continue
        part_type = part.get("type")
        if part_type in {"text", "input_text", "output_text"}:
            blocks.append({"type": "text", "text": str(part.get("text") or "")})
        elif part_type == "refusal":
            blocks.append({"type": "text", "text": str(part.get("refusal") or "")})
        elif part_type == "image_url":
            image_url = (part.get("image_url") or {}).get("url", "")
            if image_url:
                blocks.append({"type": "text", "text": f"[image] {image_url}"})
        else:
            text_value = part.get("text")
            if isinstance(text_value, str) and text_value:
                blocks.append({"type": "text", "text": text_value})
    return blocks


def _tool_message_content_to_text(content: Any) -> str:
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


def _chat_messages_to_claude_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claude_messages: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def flush_tool_results() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            claude_messages.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results = []

    for message in messages:
        role = str(message.get("role") or "")
        if role == "system":
            continue
        if role == "tool":
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": str(message.get("tool_call_id") or ""),
                    "content": _tool_message_content_to_text(message.get("content")),
                }
            )
            continue
        if role == "assistant":
            flush_tool_results()
            content_blocks = _message_content_to_claude_blocks(message.get("content"))

            # Preserve reasoning_content as a thinking block so it is passed
            # back to the API on subsequent turns (required by DeepSeek v4).
            reasoning = message.get("reasoning_content")
            if reasoning and isinstance(reasoning, str) and reasoning.strip():
                content_blocks.insert(0, {"type": "thinking", "thinking": reasoning})

            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function", {})
                arguments = function.get("arguments") or "{}"
                try:
                    parsed_arguments = (
                        json.loads(arguments) if isinstance(arguments, str) else arguments
                    )
                except Exception:
                    parsed_arguments = {"_raw": arguments}
                if not isinstance(parsed_arguments, dict):
                    parsed_arguments = {"_raw": str(parsed_arguments)}
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(tool_call.get("id") or ""),
                        "name": str(function.get("name") or ""),
                        "input": parsed_arguments,
                    }
                )
            if not content_blocks:
                content_blocks = [{"type": "text", "text": ""}]
            claude_messages.append({"role": "assistant", "content": content_blocks})
            continue
        if role == "user":
            content_blocks = list(pending_tool_results)
            pending_tool_results = []
            content_blocks.extend(_message_content_to_claude_blocks(message.get("content")))
            if not content_blocks:
                content_blocks = [{"type": "text", "text": ""}]
            claude_messages.append({"role": "user", "content": content_blocks})

    flush_tool_results()
    if not claude_messages:
        claude_messages.append({"role": "user", "content": [{"type": "text", "text": ""}]})
    return claude_messages


def _inject_turn_markers(text: str, start_turn: int = 1) -> str:
    if not text.strip():
        return text
    if "LLM Running (Turn" in text:
        return text

    section_patterns = [
        ("Plan", r"(?mi)^(?:#+\s*)?Plan\s*:?\s*$"),
        ("Execution", r"(?mi)^(?:#+\s*)?Execution\s*:?\s*$"),
        ("Verification", r"(?mi)^(?:#+\s*)?Verification\s*:?\s*$"),
        ("Final Answer", r"(?mi)^(?:#+\s*)?Final Answer\s*:?\s*$"),
    ]
    matches: list[tuple[int, str, int]] = []
    for label, pattern in section_patterns:
        match = re.search(pattern, text)
        if match:
            matches.append((match.start(), label, match.end()))

    if not matches:
        return f"**LLM Running (Turn {start_turn}) ...**\n\n{text}"

    matches.sort(key=lambda item: item[0])
    rebuilt: list[str] = []
    for idx, (start, _label, _end) in enumerate(matches):
        next_start = matches[idx + 1][0] if idx + 1 < len(matches) else len(text)
        chunk = text[start:next_start].strip()
        if not chunk:
            continue
        rebuilt.append(f"**LLM Running (Turn {start_turn + len(rebuilt)}) ...**\n\n{chunk}")

    if rebuilt:
        prefix = text[: matches[0][0]].strip()
        if prefix:
            rebuilt.insert(0, f"**LLM Running (Turn {start_turn}) ...**\n\n{prefix}")
        return "\n\n".join(rebuilt)

    return f"**LLM Running (Turn {start_turn}) ...**\n\n{text}"


def _latest_turn_marker(text: str) -> int:
    matches = re.findall(r"LLM Running \(Turn (\d+)\)", str(text or ""))
    if not matches:
        return 0
    try:
        return int(matches[-1])
    except (TypeError, ValueError):
        return 0


def _extract_classic_executor_report(text: str) -> str:
    if not text:
        return ""
    if "</summary>" in text:
        tail = text.rsplit("</summary>", 1)[-1].strip()
        if tail:
            return tail
    sections = [
        part.strip()
        for part in re.split(r"\*\*LLM Running \(Turn \d+\) \.\.\.\*\*\s*", text)
        if part.strip()
    ]
    if sections:
        return sections[-1]
    return text.strip()

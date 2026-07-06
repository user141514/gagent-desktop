from __future__ import annotations

import re
from dataclasses import dataclass


HANDOFF_TOOL_PREFIX = "transfer_to_"
EXECUTOR_TOOL_NAME = "run_genericagent_executor"
FORBIDDEN_RUNTIME_TOOLS = {
    "transfer_to_code_agent",
    "transfer_to_research_agent",
}
FORBIDDEN_TOOL_REPLACEMENT = (
    "use run_genericagent_executor for file/code/browser execution"
)


@dataclass(frozen=True)
class ToolContract:
    visible_tools: set[str]
    executable_tools: set[str]
    handoff_tools: set[str]
    forbidden_tools: set[str]
    source: str


def synthetic_handoff_tool_name(agent_name: str) -> str:
    return f"{HANDOFF_TOOL_PREFIX}{str(agent_name or '').strip()}"


def build_orchestrator_tool_contract() -> ToolContract:
    executable_tools = {EXECUTOR_TOOL_NAME}
    handoff_tools = {"chat_specialist", "planner_executor"}
    visible_tools = set(executable_tools)
    visible_tools.update(
        synthetic_handoff_tool_name(agent_name) for agent_name in handoff_tools
    )
    return ToolContract(
        visible_tools=visible_tools,
        executable_tools=executable_tools,
        handoff_tools=handoff_tools,
        forbidden_tools=set(FORBIDDEN_RUNTIME_TOOLS),
        source="openai_orchestrator_runtime",
    )


def validate_visible_tools(
    tool_names: list[str],
    contract: ToolContract,
) -> dict[str, list[str]]:
    valid_tools: list[str] = []
    unknown_tools: list[str] = []
    forbidden_tools: list[str] = []
    removed_tools: list[str] = []

    for raw_name in tool_names:
        name = str(raw_name or "").strip()
        if not name:
            continue
        if name in contract.forbidden_tools:
            _append_unique(forbidden_tools, name)
            _append_unique(removed_tools, name)
            continue
        if _is_contract_tool_name(name, contract):
            _append_unique(valid_tools, name)
            continue
        _append_unique(unknown_tools, name)
        _append_unique(removed_tools, name)

    return {
        "valid_tools": valid_tools,
        "unknown_tools": unknown_tools,
        "forbidden_tools": forbidden_tools,
        "removed_tools": removed_tools,
    }


def sanitize_runtime_tool_mentions(text: str, contract: ToolContract) -> str:
    if not text:
        return text

    sanitized = str(text)
    if not contract.forbidden_tools:
        return sanitized

    forbidden_pattern = "|".join(
        re.escape(name) for name in sorted(contract.forbidden_tools, key=len, reverse=True)
    )
    not_found_pattern = re.compile(
        rf"Tool\s+(?:{forbidden_pattern})\s+not\s+found\s+in\s+agent\s+[A-Za-z0-9_-]+",
        flags=re.IGNORECASE,
    )
    action_pattern = re.compile(
        rf"\b(?:call|use|invoke)\s+(?:{forbidden_pattern})\b",
        flags=re.IGNORECASE,
    )
    bare_pattern = re.compile(
        rf"\b(?:{forbidden_pattern})\b",
        flags=re.IGNORECASE,
    )

    sanitized = not_found_pattern.sub(
        "Tool contract error: use run_genericagent_executor in this runtime",
        sanitized,
    )
    sanitized = action_pattern.sub(FORBIDDEN_TOOL_REPLACEMENT, sanitized)
    sanitized = bare_pattern.sub(EXECUTOR_TOOL_NAME, sanitized)
    return sanitized


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _is_contract_tool_name(name: str, contract: ToolContract) -> bool:
    if name in contract.visible_tools or name in contract.executable_tools:
        return True
    if name in contract.handoff_tools:
        return True
    if name.startswith(HANDOFF_TOOL_PREFIX):
        return name[len(HANDOFF_TOOL_PREFIX) :] in contract.handoff_tools
    return False

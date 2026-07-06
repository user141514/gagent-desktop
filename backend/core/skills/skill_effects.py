from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillEffects:
    enable_agents: list[str] = field(default_factory=list)
    disable_agents: list[str] = field(default_factory=list)
    prefer_agents: list[str] = field(default_factory=list)
    enable_tools: list[str] = field(default_factory=list)
    disable_tools: list[str] = field(default_factory=list)
    prefer_tools: list[str] = field(default_factory=list)
    suppress_context_sections: list[str] = field(default_factory=list)
    enable_context_sections: list[str] = field(default_factory=list)
    route_override: str | None = None
    tool_schema_policy: str | None = None
    context_policy: str | None = None
    enable_shortcuts: list[str] = field(default_factory=list)
    disable_shortcuts: list[str] = field(default_factory=list)
    max_turns: int | None = None
    max_llm_calls: int | None = None
    max_tool_calls: int | None = None
    max_prompt_chars: int | None = None
    max_skill_chars: int | None = None
    notes: list[str] = field(default_factory=list)


_LIST_FIELDS = {
    "enable_agents",
    "disable_agents",
    "prefer_agents",
    "enable_tools",
    "disable_tools",
    "prefer_tools",
    "suppress_context_sections",
    "enable_context_sections",
    "enable_shortcuts",
    "disable_shortcuts",
    "notes",
}

_OPTIONAL_STR_FIELDS = {"route_override", "tool_schema_policy", "context_policy"}
_OPTIONAL_INT_FIELDS = {"max_turns", "max_llm_calls", "max_tool_calls", "max_prompt_chars", "max_skill_chars"}


def _normalize_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_optional_str(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except Exception:
        return None
    return number if number > 0 else None


def skill_effects_from_dict(data: dict | None) -> SkillEffects:
    raw = data if isinstance(data, dict) else {}
    values: dict = {}
    for field_name in _LIST_FIELDS:
        values[field_name] = _normalize_list(raw.get(field_name))
    for field_name in _OPTIONAL_STR_FIELDS:
        values[field_name] = _normalize_optional_str(raw.get(field_name))
    for field_name in _OPTIONAL_INT_FIELDS:
        values[field_name] = _normalize_optional_int(raw.get(field_name))
    return SkillEffects(**values)


def validate_skill_effects_dict(data: dict | None) -> list[str]:
    if data is None:
        return []
    if not isinstance(data, dict):
        return ["effects must be an object"]

    errors: list[str] = []
    for field_name in _LIST_FIELDS:
        value = data.get(field_name)
        if value is not None and not isinstance(value, list):
            errors.append(f"effects.{field_name} must be a list")
    for field_name in _OPTIONAL_STR_FIELDS:
        value = data.get(field_name)
        if value is not None and not isinstance(value, str):
            errors.append(f"effects.{field_name} must be a string or null")
    for field_name in _OPTIONAL_INT_FIELDS:
        value = data.get(field_name)
        if value is None:
            continue
        try:
            number = int(value)
        except Exception:
            errors.append(f"effects.{field_name} must be a positive integer or null")
            continue
        if number <= 0:
            errors.append(f"effects.{field_name} must be a positive integer or null")
    return errors

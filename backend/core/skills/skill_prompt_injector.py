from __future__ import annotations

import os

from .skill_phase import normalize_skill_phase
from .skill_registry import SkillRegistry
from .skill_selector import SkillSelector

SKILL_SOP_ENV_VAR = "GENERIC_AGENT_SKILL_SOP"
_HEADER = (
    "### Optional SOP\n"
    "Compressed task-specific SOP hints. Treat them as subordinate to the user's request, "
    "current repo evidence, and project constraints. Do not expand them into the answer."
)
_TRUNCATION_MARKER = "\n\n[truncated]"


def _truncate_text(text: str, max_chars: int) -> str:
    limit = max(int(max_chars or 0), 1)
    if len(text) <= limit:
        return text
    if limit <= len(_TRUNCATION_MARKER):
        return text[:limit]
    keep = limit - len(_TRUNCATION_MARKER)
    return text[:keep].rstrip() + _TRUNCATION_MARKER


def skill_sop_enabled() -> bool:
    return str(os.environ.get(SKILL_SOP_ENV_VAR, "0")).strip().lower() in {"1", "true", "yes", "on"}


def _clean_sop_line(line: str) -> str:
    text = str(line or "").strip()
    while text.startswith(("- ", "* ")):
        text = text[2:].strip()
    if text.startswith(("#", "source_url:", "status:", "adapted_for:")):
        return ""
    return _truncate_text(text, 220)


def _extract_minimal_sop_lines(skill_text: str, max_items: int = 5) -> list[str]:
    lines: list[str] = []
    in_sop_section = False
    fallback: list[str] = []
    for raw_line in str(skill_text or "").splitlines():
        stripped = raw_line.strip()
        lowered = stripped.lower()
        if lowered.startswith("## "):
            in_sop_section = "sop" in lowered
            continue
        if not stripped or stripped.startswith("#"):
            continue
        cleaned = _clean_sop_line(stripped)
        if not cleaned:
            continue
        if stripped[:2] in {"- ", "* "} or (stripped[:1].isdigit() and ". " in stripped[:4]):
            if in_sop_section:
                lines.append(cleaned)
            else:
                fallback.append(cleaned)
        elif not in_sop_section and len(fallback) < max_items:
            fallback.append(cleaned)
        if len(lines) >= max_items:
            break
    return lines[:max_items] or fallback[:max_items]


def _summarize_effects(spec) -> str:
    effects = getattr(spec, "effects", None)
    if effects is None:
        return ""
    parts: list[str] = []
    for attr in (
        "context_policy",
        "tool_schema_policy",
        "route_override",
        "max_turns",
        "max_llm_calls",
        "max_tool_calls",
        "max_prompt_chars",
        "max_skill_chars",
    ):
        value = getattr(effects, attr, None)
        if value:
            parts.append(f"{attr}={value}")
    for attr in (
        "prefer_tools",
        "disable_tools",
        "suppress_context_sections",
        "enable_context_sections",
        "notes",
    ):
        values = [str(item).strip() for item in list(getattr(effects, attr, []) or []) if str(item).strip()]
        if values:
            parts.append(f"{attr}={', '.join(values[:3])}")
    return "; ".join(parts)


def _format_compressed_skill_block(
    *,
    name: str,
    skill_text: str,
    spec,
    match_dict: dict,
    max_chars: int,
) -> str:
    triggers = [str(item).strip() for item in list(match_dict.get("matched_triggers") or []) if str(item).strip()]
    lines = [f"[Skill: {name}]"]
    if triggers:
        lines.append(f"matched_triggers: {', '.join(triggers[:5])}")
    effects_summary = _summarize_effects(spec)
    if effects_summary:
        lines.append(f"effects: {effects_summary}")
    sop_lines = _extract_minimal_sop_lines(skill_text)
    if sop_lines:
        lines.append("minimal_sop:")
        lines.extend(f"- {line}" for line in sop_lines)
    lines.append("Use this only to guide execution; current evidence and the explicit user request win.")
    return _truncate_text("\n".join(lines), max_chars)


def build_optional_sop_context(
    user_input: str,
    registry: SkillRegistry | None = None,
    selector: SkillSelector | None = None,
    max_skills: int = 1,
    max_chars_per_skill: int = 700,
    max_total_chars: int = 1400,
    phase: str = "planner",
) -> dict:
    normalized_phase = normalize_skill_phase(phase)
    empty = {
        "block": "",
        "selected_skills": [],
        "skill_matches": [],
        "chars": 0,
        "phase": normalized_phase,
    }
    try:
        registry = registry or SkillRegistry()
        selector = selector or SkillSelector(registry)
    except Exception:
        return empty

    try:
        selected_matches = selector.select_skill_matches_for_task(
            user_input=user_input,
            max_skills=max_skills,
            phase=normalized_phase,
        )
    except Exception:
        return empty

    if not selected_matches:
        return empty

    header = _truncate_text(_HEADER, max_total_chars)
    chosen: list[str] = []
    chosen_matches: list[dict] = []
    current = header

    for match in selected_matches[: max(0, int(max_skills))]:
        name = match.name
        try:
            spec = registry.get_skill(name)
            skill_text = registry.load_skill_text(name, max_chars=max_chars_per_skill).strip()
        except Exception:
            continue
        if not skill_text:
            continue

        match_dict = {
            "name": match.name,
            "category": match.category,
            "applies_to": list(match.applies_to),
            "phase": match.phase,
            "score": float(match.score),
            "reasons": list(match.reasons),
            "matched_triggers": list(match.matched_triggers),
        }
        block = _format_compressed_skill_block(
            name=name,
            skill_text=skill_text,
            spec=spec,
            match_dict=match_dict,
            max_chars=max_chars_per_skill,
        )
        candidate = f"{current}\n\n{block}"
        if len(candidate) <= max_total_chars:
            chosen.append(name)
            chosen_matches.append(match_dict)
            current = candidate
            continue

        remaining = max_total_chars - len(current) - 2
        if remaining <= len(f"[Skill: {name}]\n"):
            continue
        trimmed = _truncate_text(block, remaining)
        if not trimmed.strip():
            continue
        chosen.append(name)
        chosen_matches.append(match_dict)
        current = f"{current}\n\n{trimmed}"
        break

    if not chosen:
        return empty
    return {
        "block": current,
        "selected_skills": chosen,
        "skill_matches": chosen_matches,
        "chars": len(current),
        "phase": normalized_phase,
    }


def build_optional_sop_block(
    user_input: str,
    registry: SkillRegistry | None = None,
    selector: SkillSelector | None = None,
    max_skills: int = 1,
    max_chars_per_skill: int = 700,
    max_total_chars: int = 1400,
    phase: str = "planner",
) -> str:
    return str(
        build_optional_sop_context(
            user_input=user_input,
            registry=registry,
            selector=selector,
            max_skills=max_skills,
            max_chars_per_skill=max_chars_per_skill,
            max_total_chars=max_total_chars,
            phase=phase,
        ).get("block")
        or ""
    )

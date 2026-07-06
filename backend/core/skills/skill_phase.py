from __future__ import annotations

from typing_extensions import Literal, get_args


SkillPhase = Literal["planner", "executor", "reviewer", "verifier", "postmortem"]

VALID_SKILL_PHASES = frozenset(get_args(SkillPhase))


def normalize_skill_phase(phase: str | None) -> str:
    normalized = str(phase or "planner").strip().lower() or "planner"
    return normalized if normalized in VALID_SKILL_PHASES else "planner"


def is_valid_skill_phase(phase: str | None) -> bool:
    return str(phase or "").strip().lower() in VALID_SKILL_PHASES

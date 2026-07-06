from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.runtime.execution_policy import (
    ExecutionPolicy,
    build_execution_policy_from_skills,
    execution_policy_to_dict,
)

from .skill_registry import SkillRegistry

_MEMORY_WRITE_REASON = (
    "skills may not write durable memory; they may only emit runtime metadata "
    "or future memory candidates"
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview(text: str, limit: int = 300) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    if limit <= 12:
        return value[:limit]
    return value[: limit - 12].rstrip() + " [truncated]"


@dataclass
class SkillActivation:
    activation_id: str
    run_id: str | None
    phase: str
    user_input_preview: str
    selected_skills: list[str]
    skill_matches: list[dict[str, Any]]
    prompt_chars_added: int
    optional_sop_enabled: bool
    execution_policy: dict[str, Any]
    policy_warnings: list[str]
    memory_write_allowed: bool
    memory_write_reason: str
    created_at: str


def build_skill_activation(
    user_input: str,
    phase: str,
    skill_sop_context: dict,
    registry: SkillRegistry | None = None,
    run_id: str | None = None,
) -> SkillActivation:
    registry = registry or SkillRegistry()
    selected_skills = [str(item).strip() for item in list(skill_sop_context.get("selected_skills") or []) if str(item).strip()]
    execution_policy: ExecutionPolicy = build_execution_policy_from_skills(
        selected_skills,
        registry,
        phase=phase,
    )
    policy_dict = execution_policy_to_dict(execution_policy)
    return SkillActivation(
        activation_id=uuid.uuid4().hex,
        run_id=str(run_id).strip() if str(run_id or "").strip() else None,
        phase=str(phase or "planner").strip() or "planner",
        user_input_preview=_preview(user_input, limit=300),
        selected_skills=selected_skills,
        skill_matches=list(skill_sop_context.get("skill_matches") or []),
        prompt_chars_added=int(skill_sop_context.get("chars") or 0),
        optional_sop_enabled=bool(selected_skills),
        execution_policy=policy_dict,
        policy_warnings=list(policy_dict.get("warnings") or []),
        memory_write_allowed=False,
        memory_write_reason=_MEMORY_WRITE_REASON,
        created_at=_utc_now_iso(),
    )


def export_skill_activation(
    activation: SkillActivation,
    output_dir: str | Path = "temp/skill_activations",
) -> Path:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / "skill_activations.jsonl"
    payload = asdict(activation)
    with output_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return output_path

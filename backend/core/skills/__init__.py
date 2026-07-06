from importlib import import_module

from .skill_discovery import (
    DiscoveredSkill,
    SkillDiscovery,
    find_agentskills_directories,
    find_legacy_markdown_files,
    to_manifest_entry,
)
from .skill_effects import SkillEffects, skill_effects_from_dict, validate_skill_effects_dict
from .skill_loader import DEFAULT_MAX_CHARS, load_skill_markdown
from .skill_parser import ParsedSkill, parse_skill_markdown
from .skill_phase import VALID_SKILL_PHASES, SkillPhase, is_valid_skill_phase, normalize_skill_phase
from .skill_prompt_injector import (
    SKILL_SOP_ENV_VAR,
    build_optional_sop_block,
    build_optional_sop_context,
    skill_sop_enabled,
)
from .skill_manifest import SkillManifest
from .skill_registry import DEFAULT_SKILL_SPECS, SkillRegistry, SkillSpec
from .skill_selector import CategoryMatch, SkillMatch, SkillSelector
from .skill_taxonomy import get_category_for_skill, list_categories, list_skills_by_category

__all__ = [
    "DEFAULT_MAX_CHARS",
    "DEFAULT_SKILL_SPECS",
    "DiscoveredSkill",
    "ParsedSkill",
    "SKILL_SOP_ENV_VAR",
    "CategoryMatch",
    "SkillEffects",
    "SkillDiscovery",
    "SkillManifest",
    "SkillPhase",
    "SkillRegistry",
    "SkillMatch",
    "SkillSelector",
    "SkillSpec",
    "VALID_SKILL_PHASES",
    "build_optional_sop_block",
    "build_optional_sop_context",
    "find_agentskills_directories",
    "find_legacy_markdown_files",
    "get_category_for_skill",
    "is_valid_skill_phase",
    "list_categories",
    "list_skills_by_category",
    "load_skill_markdown",
    "normalize_skill_phase",
    "parse_skill_markdown",
    "skill_effects_from_dict",
    "skill_sop_enabled",
    "to_manifest_entry",
    "validate_skill_effects_dict",
    "SkillActivation",
    "build_skill_activation",
    "export_skill_activation",
]


def __getattr__(name: str):
    if name in {"SkillActivation", "build_skill_activation", "export_skill_activation"}:
        module = import_module(".skill_activation", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

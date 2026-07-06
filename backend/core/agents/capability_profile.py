"""CapabilityProfile — mechanical constraints that define what an agent can DO.

Design constraint: ``build_agent_instructions()`` is hardcoded to use ONLY
capability language.  It must NEVER generate text like "you are a senior
developer" or "you are an expert".  The agent is a tool-use kernel, and
its instructions describe its tools, budget, and constraints.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.skills.skill_effects import SkillEffects

# ═══════════════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════════════


@dataclass
class CapabilityProfile:
    """Declares what an agent CAN DO — not a persona.

    This is a capability gating profile, not a role-playing character.
    ``description`` should say what the agent DOES (e.g. "Reviews code for bugs")
    not what the agent IS (e.g. "You are a senior developer").
    """

    name: str
    description: str  # What this agent DOES (imperative/gerund form)

    # ── Tool gating ──
    tools: list[str] = field(default_factory=list)  # allowlist (empty = all)
    disallowed_tools: list[str] = field(default_factory=list)  # blocklist

    # ── Execution budget ──
    max_turns: int = 40

    # ── Skills ──
    skills: list[str] = field(default_factory=list)

    # ── Model ──
    model: str | None = None
    effort: str = "medium"  # "low" | "medium" | "high"

    # ── Context ──
    context_policy: str = "full"  # "full" | "slim" | "read_only"

    # ── Runtime effects (from skills) ──
    effects: SkillEffects = field(default_factory=SkillEffects)


# ═══════════════════════════════════════════════════════════════════
# Profile directory resolution
# ═══════════════════════════════════════════════════════════════════


def profile_dir() -> Path:
    """Return the project-level agents/ directory.

    Priority:
    1. ``GA_AGENTS_DIR`` environment variable
    2. ``<project_root>/agents/``
    3. ``~/.genericagent/agents/`` (user-level)
    """
    env_dir = os.environ.get("GA_AGENTS_DIR", "").strip()
    if env_dir:
        return Path(env_dir)

    # Project-level: two levels up from core/agents/capability_profile.py
    candidates: list[Path] = []
    try:
        project_root = Path(__file__).resolve().parent.parent.parent
        candidates.append(project_root / "agents")
    except Exception:
        pass

    # User-level
    candidates.append(
        Path(os.environ.get("USERPROFILE", os.environ.get("HOME", "~")))
        / ".genericagent"
        / "agents"
    )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    # Default to project-level even if it doesn't exist yet
    return candidates[0] if candidates else Path("agents")


# ═══════════════════════════════════════════════════════════════════
# YAML frontmatter parsing
# ═══════════════════════════════════════════════════════════════════


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-style frontmatter from markdown.

    Returns (frontmatter_dict, body_text).
    Frontmatter is ``---`` delimited at the very start.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if len(lines) < 2 or lines[0].strip() != "---":
        return {}, text

    # Find closing delimiter
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break

    if close_idx is None:
        return {}, text

    frontmatter_lines = lines[1:close_idx]
    body = "\n".join(lines[close_idx + 1 :]).lstrip()

    # Simple YAML-like parser (handles lists with [] syntax and scalars)
    result: dict[str, Any] = {}
    current_key: str | None = None
    for line in frontmatter_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            # Parse list syntax: [item1, item2, ...]
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1]
                items = [item.strip().strip("'").strip('"') for item in inner.split(",") if item.strip()]
                result[key] = items
            elif value.lower() in ("true", "false"):
                result[key] = value.lower() == "true"
            elif value.isdigit():
                result[key] = int(value)
            elif value in ("null", "none", "~", ""):
                result[key] = None
            else:
                # Strip quotes
                val = value
                if (val.startswith('"') and val.endswith('"')) or (
                    val.startswith("'") and val.endswith("'")
                ):
                    val = val[1:-1]
                result[key] = val
            current_key = key
        elif current_key and stripped:
            # Only append if the line looks like a continuation (indented or starts without key-like prefix)
            if stripped.startswith(("- ", "* ", "  ", "\t")) or not re.match(
                r'^[a-zA-Z_][a-zA-Z0-9_]*\s*:', stripped
            ):
                v = str(result.get(current_key, ""))
                result[current_key] = v + " " + stripped

    return result, body


def _normalize_list(value: Any) -> list[str]:
    """Normalize a value to a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


# ═══════════════════════════════════════════════════════════════════
# Profile loading
# ═══════════════════════════════════════════════════════════════════


def load_profile_from_md(path: str | Path) -> CapabilityProfile | None:
    """Load a CapabilityProfile from a markdown file with YAML frontmatter.

    Expected format::

        ---
        name: code-reviewer
        description: Reviews code for bugs and security issues
        tools: [file_read, grep, glob, web_search]
        disallowed_tools: [file_write, file_patch, code_run]
        max_turns: 10
        effort: high
        context_policy: read_only
        ---
        # Optional body (supplementary instructions)

    Returns None if the file doesn't exist or has no valid frontmatter.
    """
    path = Path(path)
    if not path.is_file():
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    fm, body = _parse_frontmatter(text)
    if not fm:
        return None

    name = str(fm.get("name", "")).strip()
    if not name:
        # Fall back to filename
        name = path.stem

    description = str(fm.get("description", "")).strip()
    if not description and body:
        description = body[:200].strip()

    return CapabilityProfile(
        name=name,
        description=description,
        tools=_normalize_list(fm.get("tools")),
        disallowed_tools=_normalize_list(fm.get("disallowed_tools")),
        max_turns=int(fm.get("max_turns", 40)),
        skills=_normalize_list(fm.get("skills")),
        model=fm.get("model"),
        effort=str(fm.get("effort", "medium")).lower(),
        context_policy=str(fm.get("context_policy", "full")).lower(),
        effects=SkillEffects(
            disable_tools=_normalize_list(fm.get("disallowed_tools")),
            max_turns=int(fm.get("max_turns", 40)),
            context_policy=str(fm.get("context_policy", "full")).lower(),
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# Profile manager
# ═══════════════════════════════════════════════════════════════════


class ProfileManager:
    """Load, cache, and query CapabilityProfiles from a directory."""

    def __init__(self, profiles_dir: str | Path | None = None) -> None:
        self._dir = Path(profiles_dir) if profiles_dir else profile_dir()
        self._cache: dict[str, CapabilityProfile] = {}
        self._loaded = False

    @property
    def profiles_dir(self) -> Path:
        return self._dir

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._dir.is_dir():
            return
        for md_file in sorted(self._dir.glob("*.md")):
            profile = load_profile_from_md(md_file)
            if profile is not None:
                self._cache[profile.name] = profile

    def get_profile(self, name: str) -> CapabilityProfile | None:
        """Get a profile by name. Returns None if not found."""
        self._ensure_loaded()
        return self._cache.get(name.rstrip())

    def list_profiles(self) -> list[CapabilityProfile]:
        """List all loaded profiles, sorted by name."""
        self._ensure_loaded()
        return sorted(self._cache.values(), key=lambda p: p.name)

    def reload(self) -> None:
        """Clear cache and re-scan the directory."""
        self._cache.clear()
        self._loaded = False
        self._ensure_loaded()


# ═══════════════════════════════════════════════════════════════════
# Instruction builder (PHILOSOPHICALLY CONSTRAINED)
# ═══════════════════════════════════════════════════════════════════


def build_agent_instructions(profile: CapabilityProfile) -> str:
    """Generate capability-focused system instructions from a profile.

    **CRITICAL PHILOSOPHICAL CONSTRAINT**: This method MUST only use
    capability/constraint language. It MUST NOT generate persona/role-play
    text like "you are a senior developer" or "you are an expert".

    The output describes: allowed tools, restricted tools, constraints,
    and skills. The agent is addressed as "you are a tool-use kernel."
    """
    lines: list[str] = []

    # ── Header ──
    lines.append(f"## CAPABILITY: {profile.name}")
    lines.append("")
    lines.append(profile.description.strip())
    lines.append("")

    # ── Allowed tools ──
    if profile.tools:
        lines.append("### ALLOWED TOOLS")
        lines.append(
            "You may ONLY use the following tools. Any other tool call will be blocked."
        )
        for tool in sorted(profile.tools):
            lines.append(f"- `{tool}`")
        lines.append("")

    # ── Restricted tools ──
    if profile.disallowed_tools:
        lines.append("### RESTRICTED TOOLS")
        lines.append(
            "The following tools are BLOCKED. Attempting to use them will fail."
        )
        for tool in sorted(profile.disallowed_tools):
            lines.append(f"- `{tool}` (blocked)")
        lines.append("")

    # ── Constraints ──
    lines.append("### CONSTRAINTS")
    lines.append(f"- Maximum turns: {profile.max_turns}")
    if profile.context_policy != "full":
        lines.append(f"- Context policy: {profile.context_policy}")
    if profile.effort != "medium":
        lines.append(f"- Effort level: {profile.effort}")
    if profile.model:
        lines.append(f"- Model: {profile.model}")
    if profile.effects.max_prompt_chars:
        lines.append(f"- Max prompt characters: {profile.effects.max_prompt_chars}")
    if profile.effects.max_llm_calls:
        lines.append(f"- Max LLM calls: {profile.effects.max_llm_calls}")
    lines.append("")

    # ── Skills ──
    if profile.skills:
        lines.append("### LOADED SKILLS")
        for skill in profile.skills:
            lines.append(f"- {skill}")
        lines.append("")

    # ── Identity (capability-based, NOT persona-based) ──
    lines.append("### IDENTITY")
    lines.append(
        "You are a tool-use kernel with the capabilities and constraints "
        "listed above. Execute the requested task within these boundaries. "
        "Do not pretend to be a human expert — you are a constrained "
        "execution environment."
    )

    return "\n".join(lines)

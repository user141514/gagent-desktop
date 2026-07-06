from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .skill_manifest import SkillManifest
from .skill_parser import ParsedSkill, parse_skill_markdown


@dataclass(frozen=True)
class DiscoveredSkill:
    name: str
    description: str
    content: str
    triggers: list[str]
    keywords: list[str]
    inputs: list[str]
    category: str
    applies_to: list[str]
    enabled: bool
    max_chars: int
    source_path: str
    format: str
    has_scripts: bool
    has_references: bool
    has_assets: bool
    has_mcp: bool
    risk_level: str
    import_status: str
    source_url: str
    source_scope: str
    priority: int
    shadowed_by: str | None = None


def find_agentskills_directories(skill_dir: Path) -> list[Path]:
    if not skill_dir.is_dir():
        return []
    return sorted(
        [
            child
            for child in skill_dir.iterdir()
            if child.is_dir() and (child / "SKILL.md").is_file()
        ],
        key=lambda path: path.name.lower(),
    )


def find_legacy_markdown_files(skill_dir: Path) -> list[Path]:
    if not skill_dir.is_dir():
        return []
    return sorted(
        [
            child
            for child in skill_dir.iterdir()
            if child.is_file() and child.suffix.lower() == ".md" and child.name.lower() != "skill.md"
        ],
        key=lambda path: path.name.lower(),
    )


def to_manifest_entry(discovered_skill: DiscoveredSkill) -> dict:
    return {
        "name": discovered_skill.name,
        "category": discovered_skill.category or "context",
        "description": discovered_skill.description,
        "triggers": list(discovered_skill.triggers),
        "negative_triggers": [],
        "source_url": discovered_skill.source_url,
        "local_file": discovered_skill.source_path,
        "enabled": bool(discovered_skill.enabled),
        "import_status": discovered_skill.import_status,
        "max_chars": int(discovered_skill.max_chars),
        "risk_level": discovered_skill.risk_level,
        "applies_to": list(discovered_skill.applies_to),
        "requires_tools": False,
    }


class SkillDiscovery:
    _PRIORITY = {"builtin": 100, "user": 200, "project": 300}

    def __init__(
        self,
        work_dir: str | Path | None = None,
        include_user: bool = True,
        include_project: bool = True,
        include_builtin: bool = True,
        include_public: bool = False,
    ):
        self.work_dir = Path(work_dir).resolve() if work_dir is not None else Path.cwd().resolve()
        self.include_user = bool(include_user)
        self.include_project = bool(include_project)
        self.include_builtin = bool(include_builtin)
        self.include_public = bool(include_public)
        self.manifest = SkillManifest()
        self.disabled_reasons: list[str] = []

    def _builtin_dir(self) -> Path:
        return Path(__file__).resolve().parent / "imported"

    def _user_dirs(self) -> list[Path]:
        home = Path.home()
        return [home / ".genericagent" / "skills", home / ".agents" / "skills"]

    def _project_dirs(self) -> list[Path]:
        return [self.work_dir / ".agents" / "skills", self.work_dir / ".genericagent" / "skills"]

    def _merge_with_manifest(self, parsed: ParsedSkill, source_scope: str, priority: int) -> DiscoveredSkill:
        manifest_entry = self.manifest.get(parsed.name) if source_scope == "builtin" else None

        if manifest_entry is not None:
            description = str(manifest_entry.get("description") or parsed.description).strip()
            triggers = [str(item) for item in list(manifest_entry.get("triggers") or parsed.triggers)]
            category = str(manifest_entry.get("category") or parsed.category).strip()
            applies_to = [str(item) for item in list(manifest_entry.get("applies_to") or parsed.applies_to)]
            enabled = bool(manifest_entry.get("enabled"))
            max_chars = int(manifest_entry.get("max_chars") or parsed.max_chars)
            risk_level = str(manifest_entry.get("risk_level") or parsed.risk_level).strip() or "medium"
            import_status = str(manifest_entry.get("import_status") or parsed.import_status).strip() or "imported"
            source_url = str(manifest_entry.get("source_url") or parsed.source_url).strip()
        else:
            description = parsed.description
            triggers = list(parsed.triggers)
            category = parsed.category
            applies_to = list(parsed.applies_to)
            enabled = False if source_scope in {"project", "user"} else parsed.enabled
            max_chars = parsed.max_chars
            risk_level = "medium" if source_scope in {"project", "user"} else parsed.risk_level
            import_status = "discovered" if source_scope in {"project", "user"} else parsed.import_status
            source_url = parsed.source_url

        if source_scope in {"project", "user"}:
            enabled = False
            import_status = "discovered"
            risk_level = "medium"

        return DiscoveredSkill(
            name=parsed.name,
            description=description,
            content=parsed.content,
            triggers=triggers,
            keywords=list(parsed.keywords),
            inputs=list(parsed.inputs),
            category=category,
            applies_to=applies_to or ["planner"],
            enabled=enabled,
            max_chars=max_chars,
            source_path=parsed.source_path,
            format=parsed.format,
            has_scripts=parsed.has_scripts,
            has_references=parsed.has_references,
            has_assets=parsed.has_assets,
            has_mcp=parsed.has_mcp,
            risk_level=risk_level,
            import_status=import_status,
            source_url=source_url,
            source_scope=source_scope,
            priority=priority,
        )

    def _discover_from_dir(self, skill_dir: Path, source_scope: str) -> list[DiscoveredSkill]:
        if not skill_dir.is_dir():
            return []
        priority = self._PRIORITY[source_scope]
        results: list[DiscoveredSkill] = []

        for directory in find_agentskills_directories(skill_dir):
            parsed = parse_skill_markdown(directory / "SKILL.md")
            results.append(self._merge_with_manifest(parsed, source_scope=source_scope, priority=priority))

        for markdown_file in find_legacy_markdown_files(skill_dir):
            parsed = parse_skill_markdown(markdown_file)
            results.append(self._merge_with_manifest(parsed, source_scope=source_scope, priority=priority))

        return results

    @staticmethod
    def _apply_shadowing(skills: list[DiscoveredSkill]) -> list[DiscoveredSkill]:
        winners: dict[str, DiscoveredSkill] = {}
        for skill in sorted(skills, key=lambda item: (-item.priority, item.name, item.source_path)):
            current = winners.get(skill.name)
            if current is None:
                winners[skill.name] = skill

        resolved: list[DiscoveredSkill] = []
        for skill in skills:
            winner = winners.get(skill.name)
            shadowed_by = None
            if winner is not None and (winner.source_path != skill.source_path or winner.priority != skill.priority):
                shadowed_by = winner.source_path
            resolved.append(
                DiscoveredSkill(
                    name=skill.name,
                    description=skill.description,
                    content=skill.content,
                    triggers=list(skill.triggers),
                    keywords=list(skill.keywords),
                    inputs=list(skill.inputs),
                    category=skill.category,
                    applies_to=list(skill.applies_to),
                    enabled=skill.enabled,
                    max_chars=skill.max_chars,
                    source_path=skill.source_path,
                    format=skill.format,
                    has_scripts=skill.has_scripts,
                    has_references=skill.has_references,
                    has_assets=skill.has_assets,
                    has_mcp=skill.has_mcp,
                    risk_level=skill.risk_level,
                    import_status=skill.import_status,
                    source_url=skill.source_url,
                    source_scope=skill.source_scope,
                    priority=skill.priority,
                    shadowed_by=shadowed_by,
                )
            )
        return sorted(resolved, key=lambda item: (-item.priority, item.name.lower(), item.source_path.lower()))

    def discover(self) -> list[DiscoveredSkill]:
        self.disabled_reasons = []
        discovered: list[DiscoveredSkill] = []

        if self.include_builtin:
            discovered.extend(self._discover_from_dir(self._builtin_dir(), source_scope="builtin"))

        if self.include_user:
            for skill_dir in self._user_dirs():
                discovered.extend(self._discover_from_dir(skill_dir, source_scope="user"))

        if self.include_project:
            for skill_dir in self._project_dirs():
                discovered.extend(self._discover_from_dir(skill_dir, source_scope="project"))

        if self.include_public:
            self.disabled_reasons.append("public skill discovery is disabled in offline mode")

        return self._apply_shadowing(discovered)

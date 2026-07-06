from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .skill_discovery import DiscoveredSkill, SkillDiscovery
from .skill_effects import SkillEffects, skill_effects_from_dict
from .skill_loader import DEFAULT_MAX_CHARS, load_skill_markdown
from .skill_manifest import SkillManifest


@dataclass(frozen=True)
class SkillSpec:
    name: str
    category: str
    description: str
    triggers: list[str]
    negative_triggers: list[str]
    source_url: str
    file_path: str
    max_chars: int = DEFAULT_MAX_CHARS
    enabled: bool = True
    import_status: str = "imported"
    risk_level: str = "low"
    applies_to: list[str] = field(default_factory=lambda: ["planner"])
    requires_tools: bool = False
    effects: SkillEffects = field(default_factory=SkillEffects)


def _skills_dir() -> Path:
    return Path(__file__).resolve().parent


def _imported_path(name: str) -> str:
    return str(_skills_dir() / "imported" / f"{name}.md")


DEFAULT_SKILL_SPECS: list[SkillSpec] = [
    SkillSpec(
        name="performance-optimization",
        category="optimization",
        description="Profile-guided tactics for reducing runtime cost and repeated work.",
        triggers=["优化运行速度", "运行速度", "速度慢", "太慢", "耗时", "延迟", "性能", "profile", "profiler", "audit", "latency"],
        negative_triggers=[],
        source_url="https://github.com/addyosmani/agent-skills/tree/main/skills/performance-optimization",
        file_path=_imported_path("performance-optimization"),
        max_chars=1800,
        enabled=True,
        applies_to=["planner", "postmortem"],
        effects=SkillEffects(
            suppress_context_sections=["long_history", "full_memory_dump"],
            tool_schema_policy="slim",
            max_prompt_chars=12000,
            notes=["profile before optimizing"],
        ),
    ),
    SkillSpec(
        name="debugging-and-error-recovery",
        category="debugging",
        description="Structured debugging SOP for failures, exceptions, and recovery steps.",
        triggers=["报错", "异常", "失败", "traceback", "error", "debug", "崩了", "不可用"],
        negative_triggers=[],
        source_url="https://github.com/addyosmani/agent-skills/tree/main/skills/debugging-and-error-recovery",
        file_path=_imported_path("debugging-and-error-recovery"),
        max_chars=1800,
        enabled=True,
        applies_to=["planner", "executor", "postmortem"],
        effects=SkillEffects(
            prefer_tools=["file_read", "code_run"],
            notes=["capture error before modifying"],
        ),
    ),
    SkillSpec(
        name="incremental-implementation",
        category="implementation",
        description="Minimal-step implementation guidance that avoids broad refactors.",
        triggers=["下一步", "最小实现", "最小改动", "小步", "一步一步", "不要大重构", "codex 提示词", "codex prompt"],
        negative_triggers=[],
        source_url="https://github.com/addyosmani/agent-skills/tree/main/skills/incremental-implementation",
        file_path=_imported_path("incremental-implementation"),
        max_chars=1800,
        enabled=True,
        applies_to=["planner", "executor"],
        effects=SkillEffects(
            max_turns=4,
            suppress_context_sections=["unrelated_skills"],
            notes=["prefer minimal file changes"],
        ),
    ),
    SkillSpec(
        name="planning-and-task-breakdown",
        category="planning",
        description="Read-first planning SOP for scoping, staged delivery, and risk framing.",
        triggers=["规划", "拆解", "任务拆分", "plan", "planning", "roadmap", "方案", "架构计划", "分阶段", "步骤"],
        negative_triggers=[],
        source_url="https://github.com/addyosmani/agent-skills/tree/main/skills/planning-and-task-breakdown",
        file_path=_imported_path("planning-and-task-breakdown"),
        max_chars=1800,
        enabled=True,
        applies_to=["planner"],
        effects=SkillEffects(
            disable_tools=["file_write", "file_patch", "shell"],
            context_policy="read_only_planning",
            notes=["planning phase should be read-only"],
        ),
    ),
    SkillSpec(
        name="test-driven-development",
        category="testing",
        description="Testing-first workflow guidance for verification, regression safety, and acceptance checks.",
        triggers=["测试", "单测", "pytest", "test", "TDD", "验证", "回归", "验收标准", "怎么验证", "自检"],
        negative_triggers=[],
        source_url="https://github.com/addyosmani/agent-skills/tree/main/skills/test-driven-development",
        file_path=_imported_path("test-driven-development"),
        max_chars=1800,
        enabled=True,
        applies_to=["planner", "verifier"],
        effects=SkillEffects(
            prefer_tools=["run_tests", "code_run"],
            notes=["define verification before implementation"],
        ),
    ),
]


class SkillRegistry:
    def __init__(
        self,
        specs: list[SkillSpec] | None = None,
        include_discovered: bool = False,
        work_dir: str | Path | None = None,
    ) -> None:
        self._skills: dict[str, SkillSpec] = {}
        self._discovered_skills: list[DiscoveredSkill] = []
        for spec in specs or self._load_default_specs():
            self.register_skill(spec)
        if include_discovered:
            try:
                self._discovered_skills = SkillDiscovery(work_dir=work_dir).discover()
            except Exception:
                self._discovered_skills = []

    @staticmethod
    def _manifest_entry_to_spec(entry: dict, manifest: SkillManifest) -> SkillSpec:
        return SkillSpec(
            name=str(entry.get("name") or "").strip(),
            category=str(entry.get("category") or "").strip(),
            description=str(entry.get("description") or "").strip(),
            triggers=[str(item) for item in list(entry.get("triggers") or [])],
            negative_triggers=[str(item) for item in list(entry.get("negative_triggers") or [])],
            source_url=str(entry.get("source_url") or "").strip(),
            file_path=str(manifest._resolve_local_file(entry)),
            max_chars=int(entry.get("max_chars") or DEFAULT_MAX_CHARS),
            enabled=bool(entry.get("enabled")),
            import_status=str(entry.get("import_status") or "imported"),
            risk_level=str(entry.get("risk_level") or "low"),
            applies_to=[str(item) for item in list(entry.get("applies_to") or [])],
            requires_tools=bool(entry.get("requires_tools")),
            effects=skill_effects_from_dict(entry.get("effects")),
        )

    def _load_default_specs(self) -> list[SkillSpec]:
        try:
            manifest = SkillManifest()
            if manifest.validate():
                return DEFAULT_SKILL_SPECS
            specs = [
                self._manifest_entry_to_spec(entry, manifest)
                for entry in manifest.list_imported_enabled()
            ]
            return specs or DEFAULT_SKILL_SPECS
        except Exception:
            return DEFAULT_SKILL_SPECS

    def list_skills(self) -> list[SkillSpec]:
        return sorted(self._skills.values(), key=lambda spec: spec.name)

    def list_discovered_skills(self) -> list[DiscoveredSkill]:
        return list(self._discovered_skills)

    def get_skill(self, name: str) -> SkillSpec | None:
        return self._skills.get(str(name or "").strip())

    def register_skill(self, spec: SkillSpec) -> None:
        self._skills[spec.name] = spec

    def load_skill_text(self, name: str, max_chars: int | None = None) -> str:
        spec = self.get_skill(name)
        if spec is None:
            raise KeyError(f"Unknown skill: {name}")
        limit = spec.max_chars if max_chars is None else min(int(max_chars), int(spec.max_chars))
        return load_skill_markdown(spec.file_path, max_chars=limit)

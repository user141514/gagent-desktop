from __future__ import annotations

from dataclasses import dataclass

from .skill_manifest import SkillManifest
from .skill_phase import normalize_skill_phase
from .skill_registry import SkillRegistry


@dataclass(frozen=True)
class CategoryMatch:
    category: str
    score: float
    reasons: list[str]
    matched_triggers: list[str]


@dataclass(frozen=True)
class SkillMatch:
    name: str
    category: str
    applies_to: list[str]
    phase: str
    score: float
    reasons: list[str]
    matched_triggers: list[str]


def _normalize_text(user_input: str, context: dict | None = None) -> str:
    parts = [str(user_input or "").strip(), str(context or "").strip()]
    return " ".join(part.lower() for part in parts if part)


class SkillSelector:
    _TIEBREAK_ORDER = {
        "debugging-and-error-recovery": 0,
        "performance-optimization": 1,
        "test-driven-development": 2,
        "planning-and-task-breakdown": 3,
        "incremental-implementation": 4,
    }

    _CATEGORY_RULES = {
        "optimization": {
            "weight": 3.0,
            "triggers": [
                "\u4f18\u5316\u8fd0\u884c\u901f\u5ea6",
                "\u8fd0\u884c\u901f\u5ea6",
                "\u901f\u5ea6\u6162",
                "\u592a\u6162",
                "\u8017\u65f6",
                "\u5ef6\u8fdf",
                "\u6027\u80fd",
                "profile",
                "profiler",
                "audit",
                "latency",
            ],
        },
        "debugging": {
            "weight": 3.0,
            "triggers": [
                "\u62a5\u9519",
                "\u5f02\u5e38",
                "\u5931\u8d25",
                "traceback",
                "error",
                "debug",
                "\u5d29\u4e86",
                "\u4e0d\u53ef\u7528",
            ],
        },
        "testing": {
            "weight": 3.0,
            "triggers": [
                "\u6d4b\u8bd5",
                "\u5355\u6d4b",
                "pytest",
                "test",
                "tdd",
                "\u9a8c\u8bc1",
                "\u56de\u5f52",
                "\u9a8c\u6536\u6807\u51c6",
                "\u600e\u4e48\u9a8c\u8bc1",
                "\u81ea\u68c0",
            ],
        },
        "planning": {
            "weight": 2.5,
            "triggers": [
                "\u89c4\u5212",
                "\u62c6\u89e3",
                "\u4efb\u52a1\u62c6\u5206",
                "plan",
                "planning",
                "roadmap",
                "\u65b9\u6848",
                "\u67b6\u6784\u8ba1\u5212",
                "\u5206\u9636\u6bb5",
                "\u6b65\u9aa4",
            ],
        },
        "implementation": {
            "weight": 2.0,
            "triggers": [
                "\u4e0b\u4e00\u6b65",
                "\u6700\u5c0f\u5b9e\u73b0",
                "\u6700\u5c0f\u6539\u52a8",
                "\u5c0f\u6b65",
                "\u4e00\u6b65\u4e00\u6b65",
                "\u4e0d\u8981\u5927\u91cd\u6784",
                "codex \u63d0\u793a\u8bcd",
                "codex prompt",
            ],
        },
        "review": {
            "weight": 2.0,
            "triggers": ["\u5ba1\u67e5", "review", "\u8d28\u91cf", "code review"],
        },
        "security": {
            "weight": 3.0,
            "triggers": ["\u5b89\u5168", "\u6f0f\u6d1e", "\u6743\u9650", "\u6ce8\u5165", "security"],
        },
        "documentation": {
            "weight": 2.0,
            "triggers": ["\u6587\u6863", "readme", "adr", "documentation"],
        },
        "architecture": {
            "weight": 2.0,
            "triggers": ["api", "\u63a5\u53e3", "interface", "contract", "schema"],
        },
        "workflow": {
            "weight": 2.0,
            "triggers": ["git", "branch", "commit", "\u7248\u672c", "workflow", "ci", "cd", "pipeline", "automation"],
        },
        "context": {
            "weight": 2.0,
            "triggers": ["context", "\u4e0a\u4e0b\u6587", "prompt scaffolding"],
        },
    }

    _SKILL_WEIGHTS = {
        "performance-optimization": 3.0,
        "debugging-and-error-recovery": 3.0,
        "test-driven-development": 3.0,
        "planning-and-task-breakdown": 2.5,
        "incremental-implementation": 2.0,
    }

    def __init__(self, registry: SkillRegistry | None = None, manifest: SkillManifest | None = None) -> None:
        self.registry = registry or SkillRegistry()
        self.manifest = manifest or SkillManifest()

    def select_category_matches_for_task(
        self,
        user_input: str,
        context: dict | None = None,
    ) -> list[CategoryMatch]:
        text = _normalize_text(user_input, context)
        if not text:
            return []

        matches: list[CategoryMatch] = []
        for category, rule in self._CATEGORY_RULES.items():
            matched_triggers: list[str] = []
            reasons: list[str] = []
            score = 0.0
            for trigger in rule["triggers"]:
                if str(trigger).lower() not in text:
                    continue
                matched_triggers.append(trigger)
                score += float(rule["weight"])
                reasons.append(f"category matched: {category}")
                reasons.append(f"matched category trigger: {trigger}")
                reasons.append(f"score +{rule['weight']} for {category} category")
            if score <= 0:
                continue
            matches.append(
                CategoryMatch(
                    category=category,
                    score=score,
                    reasons=reasons,
                    matched_triggers=matched_triggers,
                )
            )

        matches.sort(key=lambda item: (-item.score, item.category))
        return matches

    @staticmethod
    def _phase_allowed(spec, phase: str) -> bool:
        allowed = [str(item or "").strip().lower() for item in list(spec.applies_to or []) if str(item or "").strip()]
        return phase in allowed

    def _score_skill(self, spec, text: str, category_match: CategoryMatch, phase: str) -> SkillMatch | None:
        if not spec.enabled or not self._phase_allowed(spec, phase):
            return None

        for trigger in spec.negative_triggers:
            if str(trigger).lower() in text:
                return None

        weight = float(self._SKILL_WEIGHTS.get(spec.name, category_match.score or 1.0))
        score = 0.0
        reasons = [f"category matched: {spec.category}", f"phase allowed: {phase}"]
        matched_triggers: list[str] = []
        for trigger in spec.triggers:
            normalized = str(trigger).lower()
            if normalized not in text:
                continue
            matched_triggers.append(trigger)
            score += weight
            if spec.name == "incremental-implementation":
                reasons.append(f"matched workflow trigger: {trigger}")
                reasons.append(f"score +{weight:.0f} for incremental workflow intent")
            elif spec.name == "planning-and-task-breakdown":
                reasons.append(f"matched planning trigger: {trigger}")
                reasons.append(f"score +{weight:.1f} for planning intent")
            elif spec.name == "test-driven-development":
                reasons.append(f"matched testing trigger: {trigger}")
                reasons.append(f"score +{weight:.0f} for testing intent")
            elif spec.name == "performance-optimization":
                reasons.append(f"matched strong trigger: {trigger}")
                reasons.append(f"score +{weight:.0f} for performance intent")
            elif spec.name == "debugging-and-error-recovery":
                reasons.append(f"matched strong trigger: {trigger}")
                reasons.append(f"score +{weight:.0f} for debugging intent")
            else:
                reasons.append(f"matched strong trigger: {trigger}")
                reasons.append(f"score +{weight:.0f} for skill intent")

        if score <= 0:
            return None
        return SkillMatch(
            name=spec.name,
            category=spec.category,
            applies_to=list(spec.applies_to),
            phase=phase,
            score=score,
            reasons=reasons,
            matched_triggers=matched_triggers,
        )

    def select_skill_matches_for_task(
        self,
        user_input: str,
        context: dict | None = None,
        max_skills: int = 2,
        phase: str = "planner",
    ) -> list[SkillMatch]:
        text = _normalize_text(user_input, context)
        if not text:
            return []

        normalized_phase = normalize_skill_phase(phase)
        category_matches = self.select_category_matches_for_task(user_input, context=context)
        if not category_matches:
            return []
        category_map = {match.category: match for match in category_matches}

        matches: list[SkillMatch] = []
        for spec in self.registry.list_skills():
            category_match = category_map.get(spec.category)
            if category_match is None:
                continue
            match = self._score_skill(spec, text, category_match, normalized_phase)
            if match is not None and match.score > 0:
                matches.append(match)

        matches.sort(
            key=lambda match: (
                -match.score,
                self._TIEBREAK_ORDER.get(match.name, 999),
                match.name,
            )
        )
        return matches[: max(0, int(max_skills))]

    def select_skills_for_task(
        self,
        user_input: str,
        context: dict | None = None,
        max_skills: int = 2,
        phase: str = "planner",
    ) -> list[str]:
        return [
            match.name
            for match in self.select_skill_matches_for_task(
                user_input=user_input,
                context=context,
                max_skills=max_skills,
                phase=phase,
            )
        ]

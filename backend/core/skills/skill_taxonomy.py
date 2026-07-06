from __future__ import annotations


_CATEGORY_TO_SKILLS = {
    "optimization": [
        "performance-optimization",
        "code-simplification",
    ],
    "debugging": [
        "debugging-and-error-recovery",
    ],
    "implementation": [
        "incremental-implementation",
    ],
    "planning": [
        "planning-and-task-breakdown",
    ],
    "review": [
        "code-review-and-quality",
    ],
    "testing": [
        "test-driven-development",
    ],
    "security": [
        "security-and-hardening",
    ],
    "documentation": [
        "documentation-and-adrs",
    ],
    "architecture": [
        "api-and-interface-design",
    ],
    "workflow": [
        "git-workflow-and-versioning",
        "ci-cd-and-automation",
    ],
    "context": [
        "context-engineering",
    ],
    "frontend": [],
}

_SKILL_TO_CATEGORY = {
    skill_name: category
    for category, skill_names in _CATEGORY_TO_SKILLS.items()
    for skill_name in skill_names
}


def get_category_for_skill(name: str) -> str | None:
    return _SKILL_TO_CATEGORY.get(str(name or "").strip())


def list_categories() -> list[str]:
    return sorted(_CATEGORY_TO_SKILLS.keys())


def list_skills_by_category(category: str) -> list[str]:
    return sorted(_CATEGORY_TO_SKILLS.get(str(category or "").strip(), []))

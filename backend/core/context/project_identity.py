"""
Project identity — generate a stable project_id and detect project structure.

Uses filesystem inspection of the project root directory.
Returns ProjectIdentity or None when disabled.
"""

import hashlib
import os
import time
from dataclasses import dataclass, field

from . import _context_enabled

# Files that indicate a project root and their associated languages
_KEY_FILE_MAP: dict[str, list[str]] = {
    "pyproject.toml": ["python"],
    "setup.py": ["python"],
    "setup.cfg": ["python"],
    "requirements.txt": ["python"],
    "Pipfile": ["python"],
    "package.json": ["javascript", "typescript"],
    "tsconfig.json": ["typescript"],
    "next.config.js": ["javascript", "typescript"],
    "next.config.ts": ["typescript"],
    "vite.config.js": ["javascript", "typescript"],
    "vite.config.ts": ["typescript"],
    "Cargo.toml": ["rust"],
    "go.mod": ["go"],
    "Makefile": [],
    "CMakeLists.txt": ["c", "cpp"],
    "Dockerfile": [],
    "docker-compose.yml": [],
    ".gitignore": [],
    "README.md": [],
    "Gemfile": ["ruby"],
    "pom.xml": ["java"],
    "build.gradle": ["java", "kotlin"],
    "build.gradle.kts": ["kotlin"],
    "pubspec.yaml": ["dart"],
    "composer.json": ["php"],
    "deno.json": ["javascript", "typescript"],
    "deno.jsonc": ["javascript", "typescript"],
}


@dataclass
class ProjectIdentity:
    """Stable identity of the project at the current workspace root."""

    project_id: str
    project_name: str
    project_root: str
    key_files: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    generated_at: float = 0.0

    def __post_init__(self):
        if self.generated_at == 0.0:
            self.generated_at = time.time()
        if len(self.key_files) > 20:
            self.key_files = self.key_files[:20]


def _make_project_id(project_root: str) -> str:
    """Deterministic project_id from the absolute project root path."""
    digest = hashlib.sha256(os.path.abspath(project_root).encode("utf-8")).hexdigest()
    return digest[:12]


def _scan_key_files(project_root: str) -> tuple[list[str], list[str]]:
    """Scan project root for known key files. Returns (key_files, languages)."""
    found_files: list[str] = []
    found_langs: set[str] = set()

    try:
        entries = os.listdir(project_root)
    except OSError:
        return [], []

    for entry in sorted(entries):
        if entry in _KEY_FILE_MAP:
            found_files.append(entry)
            for lang in _KEY_FILE_MAP[entry]:
                found_langs.add(lang)

    return found_files, sorted(found_langs)


def detect_project(project_root: str | None = None) -> ProjectIdentity | None:
    """Detect project identity from the given or detected project root.

    Returns None when GA_CONTEXT_RUNTIME_ENABLED != '1' or project_root is None.
    """
    if not _context_enabled():
        return None
    if project_root is None:
        return None

    root = os.path.abspath(project_root)
    project_id = _make_project_id(root)
    project_name = os.path.basename(root)
    key_files, languages = _scan_key_files(root)

    return ProjectIdentity(
        project_id=project_id,
        project_name=project_name,
        project_root=root,
        key_files=key_files,
        languages=languages,
        generated_at=time.time(),
    )

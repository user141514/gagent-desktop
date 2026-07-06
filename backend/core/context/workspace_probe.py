"""
Workspace probe — detect the current working directory environment.

Uses git subprocess calls to detect repository context.
Returns WorkspaceSnapshot or None when disabled.
"""

import os
import subprocess
import time
from dataclasses import dataclass, field

from . import _context_enabled


@dataclass
class WorkspaceSnapshot:
    """Point-in-time snapshot of the current working directory environment."""

    cwd: str
    git_root: str | None = None
    git_branch: str | None = None
    git_remote_url: str | None = None
    has_uncommitted_changes: bool = False
    dirty_files: list[str] = field(default_factory=list)
    detected_at: float = 0.0

    def __post_init__(self):
        if self.detected_at == 0.0:
            self.detected_at = time.time()
        # Enforce cap
        if len(self.dirty_files) > 30:
            self.dirty_files = self.dirty_files[:30]


def _run_git(args: list[str], cwd: str | None = None, timeout: float = 3.0) -> str:
    """Run a git command, return stripped stdout. Returns '' on any failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        return result.stdout.strip()
    except Exception:
        return ""


class WorkspaceProbe:
    """Detects workspace environment via git and filesystem inspection."""

    @staticmethod
    def probe(cwd: str | None = None) -> WorkspaceSnapshot | None:
        """Return a WorkspaceSnapshot for the given or current directory.

        Returns None when GA_CONTEXT_RUNTIME_ENABLED != '1'.
        """
        if not _context_enabled():
            return None

        resolved = os.path.abspath(cwd) if cwd else os.path.abspath(os.getcwd())

        git_root = _run_git(["rev-parse", "--show-toplevel"], cwd=resolved)
        git_root = os.path.abspath(git_root) if git_root else None

        git_branch = None
        git_remote_url = None
        has_uncommitted = False
        dirty_files: list[str] = []

        if git_root:
            git_branch = _run_git(["branch", "--show-current"], cwd=git_root) or None
            git_remote_url = _run_git(["remote", "get-url", "origin"], cwd=git_root) or None

            # Check for uncommitted changes
            status_out = _run_git(["status", "--porcelain"], cwd=git_root)
            if status_out:
                has_uncommitted = True
                lines = status_out.split("\n")
                for line in lines[:30]:
                    if len(line) >= 3:
                        dirty_files.append(line[3:].strip())

        return WorkspaceSnapshot(
            cwd=resolved,
            git_root=git_root,
            git_branch=git_branch,
            git_remote_url=git_remote_url,
            has_uncommitted_changes=has_uncommitted,
            dirty_files=dirty_files,
            detected_at=time.time(),
        )

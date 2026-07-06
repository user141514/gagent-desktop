"""
Shared Artifact Store — Level 4 Blackboard for multi-agent collaboration.

A thread-safe, in-memory key-value store scoped to one orchestration run.
Agents read/write artifacts by name instead of embedding large content in
handoff messages, reducing token waste and enabling structured collaboration.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Artifact:
    key: str
    content: str
    version: int
    author: str
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "content": self.content,
            "version": self.version,
            "author": self.author,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class SharedArtifactStore:
    """Thread-safe dictionary for sharing artifacts between agents during a run.

    Usage:
        store = SharedArtifactStore()
        store.write("auth.py", code, author="code_agent")
        code = store.read("auth.py")
        for a in store.list():
            print(a.key, a.version)
    """

    def __init__(self) -> None:
        self._store: dict[str, Artifact] = {}
        self._lock = threading.Lock()

    def write(self, key: str, content: str, author: str = "unknown", metadata: dict[str, Any] | None = None) -> int:
        """Write (or overwrite) an artifact. Returns the new version number."""
        with self._lock:
            existing = self._store.get(key)
            version = (existing.version + 1) if existing else 1
            self._store[key] = Artifact(
                key=key,
                content=content,
                version=version,
                author=author,
                metadata=dict(metadata or {}),
            )
            return version

    def read(self, key: str) -> Artifact | None:
        """Read an artifact by key. Returns None if not found."""
        with self._lock:
            return self._store.get(key)

    def list(self) -> list[Artifact]:
        """Return all artifacts sorted by key name."""
        with self._lock:
            return sorted(self._store.values(), key=lambda a: a.key)

    def list_keys(self) -> list[str]:
        """Return artifact key names only (lightweight, for prompt injection)."""
        with self._lock:
            return sorted(self._store.keys())

    def delete(self, key: str) -> bool:
        """Delete an artifact. Returns True if it existed."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a serializable snapshot of the store state."""
        with self._lock:
            return {k: v.to_dict() for k, v in self._store.items()}

    def workspace_summary(self) -> str:
        """Build a compact summary for injection into executor prompts."""
        keys = self.list_keys()
        if not keys:
            return "(workspace is empty)"
        lines = []
        for k in keys:
            a = self._store.get(k)
            if a is None:
                continue
            preview = a.content[:80].replace("\n", " ").strip()
            lines.append(f"  [{a.key}] v{a.version} by {a.author} — {preview}...")
        return "\n".join(lines)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def __repr__(self) -> str:
        return f"SharedArtifactStore({len(self)} artifacts)"

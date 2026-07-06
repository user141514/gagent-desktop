"""Agent input contract — structured task submission."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentInput:
    """Formal input contract for submitting a task to an agent backend.

    Replaces the positional arguments to ``put_task(query, source, images, run_id)``.
    """

    query: str
    source: str = "user"
    images: list[str] | None = None
    run_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_legacy_kwargs(self) -> dict[str, object]:
        """Convert to kwargs compatible with legacy ``put_task()``."""
        return {
            "query": self.query,
            "source": self.source,
            "images": self.images or [],
            "run_id": self.run_id,
        }

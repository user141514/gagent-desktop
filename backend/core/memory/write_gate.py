"""Hard write gate for durable memory writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing_extensions import Literal

MemoryWriteSource = Literal[
    "distiller",
    "promoter",
    "manual_user",
    "system_migration",
    "agent",
    "skill",
    "tool",
    "unknown",
]

MemoryWriteTarget = Literal[
    "memory_items",
    "memory_candidates",
    "evidence_chunks",
    "authoritative_memory",
    "memory_events",
]

_VALID_SOURCES = {
    "distiller",
    "promoter",
    "manual_user",
    "system_migration",
    "agent",
    "skill",
    "tool",
    "unknown",
}
_VALID_TARGETS = {
    "memory_items",
    "memory_candidates",
    "evidence_chunks",
    "authoritative_memory",
    "memory_events",
}
_DURABLE_SOURCES = {
    "distiller",
    "promoter",
    "manual_user",
    "system_migration",
}
_DURABLE_TARGETS = {"memory_items", "authoritative_memory"}


def _normalize_source(source: str | None) -> str:
    value = str(source or "").strip().lower()
    return value if value in _VALID_SOURCES else "unknown"


def _normalize_target(target: str | None) -> str:
    value = str(target or "").strip().lower()
    return value if value in _VALID_TARGETS else value


@dataclass
class MemoryWriteDecision:
    allowed: bool
    source: str
    target: str
    reason: str
    required_redirect: str | None = None


class MemoryWriteGate:
    def check_write(
        self,
        source: str,
        target: str,
        metadata: dict | None = None,
    ) -> MemoryWriteDecision:
        normalized_source = _normalize_source(source)
        normalized_target = _normalize_target(target)
        _ = metadata or {}

        if normalized_target not in _VALID_TARGETS:
            return MemoryWriteDecision(
                allowed=False,
                source=normalized_source,
                target=normalized_target,
                reason=f"unknown memory write target: {normalized_target}",
                required_redirect=None,
            )

        if normalized_target in _DURABLE_TARGETS:
            if normalized_source in _DURABLE_SOURCES:
                return MemoryWriteDecision(
                    allowed=True,
                    source=normalized_source,
                    target=normalized_target,
                    reason="source is authorized to write durable memory",
                    required_redirect=None,
                )
            return MemoryWriteDecision(
                allowed=False,
                source=normalized_source,
                target=normalized_target,
                reason=(
                    f"source '{normalized_source}' may only emit evidence or pending memory candidates; "
                    f"it may not write durable memory target '{normalized_target}' directly"
                ),
                required_redirect="memory_candidates",
            )

        if normalized_target == "memory_candidates":
            return MemoryWriteDecision(
                allowed=True,
                source=normalized_source,
                target=normalized_target,
                reason="memory candidates are pending, non-durable records and may be written by runtime sources",
                required_redirect=None,
            )

        if normalized_target == "evidence_chunks":
            if normalized_source == "skill":
                reason = (
                    "skill source may write evidence chunks as non-durable evidence only; "
                    "this does not grant durable memory write authority"
                )
            else:
                reason = "evidence chunks are non-durable evidence records and may be written by runtime sources"
            return MemoryWriteDecision(
                allowed=True,
                source=normalized_source,
                target=normalized_target,
                reason=reason,
                required_redirect=None,
            )

        if normalized_target == "memory_events":
            return MemoryWriteDecision(
                allowed=True,
                source=normalized_source,
                target=normalized_target,
                reason="memory events are audit records, not durable memory",
                required_redirect=None,
            )

        return MemoryWriteDecision(
            allowed=False,
            source=normalized_source,
            target=normalized_target,
            reason=f"unsupported memory write target: {normalized_target}",
            required_redirect=None,
        )

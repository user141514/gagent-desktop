"""Dataclasses for the structured memory ledger."""

from dataclasses import dataclass


@dataclass
class MemoryItem:
    id: str
    kind: str
    scope_type: str
    scope_id: str
    content: str
    summary: str | None = None
    source_path: str | None = None
    source_turn: str | None = None
    evidence_chunk_id: str | None = None
    verified: int = 0
    confidence: float = 0.5
    freshness: str | None = None
    supersedes: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class EvidenceChunk:
    id: str
    source_path: str
    content: str
    source_type: str | None = None
    actor: str | None = None
    content_hash: str | None = None
    summary: str | None = None
    project_id: str | None = None
    repo_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    turn_index: int | None = None
    created_at: str = ""


@dataclass
class MemoryCandidate:
    id: str
    source: str
    content: str
    source_id: str | None = None
    kind: str | None = None
    scope_type: str | None = None
    scope_id: str | None = None
    evidence_chunk_id: str | None = None
    confidence: float = 0.5
    status: str = "pending"
    reason: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MemoryEvent:
    id: str
    event_type: str
    created_at: str
    memory_id: str | None = None
    payload: str | None = None

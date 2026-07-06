PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    source_path TEXT,
    source_turn TEXT,
    evidence_chunk_id TEXT,
    verified INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5,
    freshness TEXT,
    supersedes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (evidence_chunk_id) REFERENCES evidence_chunks(id)
);

CREATE TABLE IF NOT EXISTS evidence_chunks (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_type TEXT,
    actor TEXT,
    content TEXT NOT NULL,
    content_hash TEXT,
    summary TEXT,
    project_id TEXT,
    repo_id TEXT,
    session_id TEXT,
    run_id TEXT,
    turn_index INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_candidates (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT,
    kind TEXT,
    scope_type TEXT,
    scope_id TEXT,
    content TEXT NOT NULL,
    evidence_chunk_id TEXT,
    confidence REAL DEFAULT 0.5,
    status TEXT DEFAULT 'pending',
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (evidence_chunk_id) REFERENCES evidence_chunks(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS evidence_chunks_fts
USING fts5(
    evidence_chunk_id UNINDEXED,
    content,
    summary,
    source_path,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS memory_events (
    id TEXT PRIMARY KEY,
    memory_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memory_items(id)
);

CREATE INDEX IF NOT EXISTS idx_memory_items_scope
ON memory_items(scope_type, scope_id);

CREATE INDEX IF NOT EXISTS idx_memory_items_kind
ON memory_items(kind);

CREATE INDEX IF NOT EXISTS idx_memory_items_verified
ON memory_items(verified);

CREATE INDEX IF NOT EXISTS idx_evidence_chunks_project_id
ON evidence_chunks(project_id);

CREATE INDEX IF NOT EXISTS idx_evidence_chunks_repo_id
ON evidence_chunks(repo_id);

CREATE INDEX IF NOT EXISTS idx_evidence_chunks_session_id
ON evidence_chunks(session_id);

CREATE INDEX IF NOT EXISTS idx_evidence_chunks_run_id
ON evidence_chunks(run_id);

CREATE INDEX IF NOT EXISTS idx_evidence_chunks_content_hash
ON evidence_chunks(content_hash);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_status
ON memory_candidates(status);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_source
ON memory_candidates(source);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_scope
ON memory_candidates(scope_type, scope_id);

CREATE INDEX IF NOT EXISTS idx_memory_events_memory_id
ON memory_events(memory_id);

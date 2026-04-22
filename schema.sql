-- Bag of Holding v0P: SQLite Schema

CREATE TABLE IF NOT EXISTS docs (
    doc_id TEXT PRIMARY KEY,
    path TEXT UNIQUE,
    type TEXT,
    status TEXT,
    version TEXT,
    updated_ts INTEGER,
    operator_state TEXT,
    operator_intent TEXT,
    plane_scope_json TEXT,
    field_scope_json TEXT,
    node_scope_json TEXT,
    text_hash TEXT,
    source_type TEXT,
    topics_tokens TEXT DEFAULT ''
);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    content,
    title,
    path,
    topics
);

CREATE TABLE IF NOT EXISTS defs (
    doc_id TEXT,
    term TEXT,
    block_hash TEXT,
    block_text TEXT,
    plane_scope_json TEXT
);

CREATE TABLE IF NOT EXISTS plane_facts (
    subject_id TEXT,
    plane_path TEXT,
    r REAL,
    d INTEGER,
    q REAL,
    c REAL,
    m TEXT,
    ts INTEGER,
    valid_until INTEGER,
    context_ref TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    doc_id TEXT,
    start_ts INTEGER,
    end_ts INTEGER,
    timezone TEXT,
    status TEXT,
    confidence REAL
);

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_type TEXT,
    doc_ids TEXT,
    term TEXT,
    plane_path TEXT,
    detected_ts INTEGER
);

CREATE INDEX IF NOT EXISTS idx_docs_status ON docs(status);
CREATE INDEX IF NOT EXISTS idx_docs_type ON docs(type);
CREATE INDEX IF NOT EXISTS idx_plane_facts_path ON plane_facts(plane_path);
CREATE INDEX IF NOT EXISTS idx_defs_term ON defs(term);
CREATE INDEX IF NOT EXISTS idx_conflicts_type ON conflicts(conflict_type);

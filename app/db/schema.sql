-- Bag of Holding v2: SQLite Schema
-- v0P columns preserved exactly. v2 additions applied via ALTER TABLE in connection.py.

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
    -- v2 additions (added via ALTER TABLE): corpus_class TEXT DEFAULT 'CORPUS_CLASS:DRAFT'
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
    -- v2 additions (added via ALTER TABLE): acknowledged INTEGER DEFAULT 0
);

-- v2: Lineage tracking table (created fresh — not ALTER TABLE)
CREATE TABLE IF NOT EXISTS lineage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    related_doc_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    detected_ts INTEGER NOT NULL,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_docs_status ON docs(status);
CREATE INDEX IF NOT EXISTS idx_docs_type ON docs(type);
CREATE INDEX IF NOT EXISTS idx_docs_corpus_class ON docs(corpus_class);
CREATE INDEX IF NOT EXISTS idx_plane_facts_path ON plane_facts(plane_path);
CREATE INDEX IF NOT EXISTS idx_defs_term ON defs(term);
CREATE INDEX IF NOT EXISTS idx_conflicts_type ON conflicts(conflict_type);
CREATE INDEX IF NOT EXISTS idx_lineage_doc_id ON lineage(doc_id);
CREATE INDEX IF NOT EXISTS idx_lineage_related ON lineage(related_doc_id);

-- Phase 8 (Daenary + DCNS): Document coordinate table
-- Stores optional Daenary semantic state dimensions per document.
-- UNIQUE(doc_id, dimension) so re-indexing replaces old rows.
CREATE TABLE IF NOT EXISTS doc_coordinates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id          TEXT    NOT NULL,
    dimension       TEXT    NOT NULL,
    state           INTEGER NOT NULL,    -- -1 | 0 | +1
    quality         REAL,               -- [0,1]
    confidence      REAL,               -- [0,1]
    mode            TEXT,               -- 'contain' | 'cancel' | NULL (only when state==0)
    observed_ts     INTEGER,
    valid_until_ts  INTEGER,
    source          TEXT    DEFAULT 'frontmatter',
    UNIQUE(doc_id, dimension)
);

CREATE INDEX IF NOT EXISTS idx_doc_coordinates_doc_id      ON doc_coordinates(doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_coordinates_dimension   ON doc_coordinates(dimension);
CREATE INDEX IF NOT EXISTS idx_doc_coordinates_state       ON doc_coordinates(state);
CREATE INDEX IF NOT EXISTS idx_doc_coordinates_valid_until ON doc_coordinates(valid_until_ts);

-- Phase 8 (Daenary + DCNS): Selective relationship edge table
-- Explicit relationships derived from lineage/conflicts, not inferred ad-hoc.
-- UNIQUE(source, target, edge_type) prevents duplicate edges from re-indexing.
CREATE TABLE IF NOT EXISTS doc_edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_doc_id   TEXT    NOT NULL,
    target_doc_id   TEXT    NOT NULL,
    edge_type       TEXT    NOT NULL,   -- duplicate_content | supersedes | conflicts | canon_relates_to | derives
    state           INTEGER,            -- +1 reinforces | 0 unresolved | -1 conflicts
    permeability    REAL,               -- flow affordance [0,1]
    load_score      REAL,               -- diagnostic only
    detected_ts     INTEGER NOT NULL,
    detail          TEXT,               -- JSON or free-text annotation
    UNIQUE(source_doc_id, target_doc_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_doc_edges_source ON doc_edges(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_edges_target ON doc_edges(target_doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_edges_type   ON doc_edges(edge_type);

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
    topics_tokens TEXT DEFAULT '',
    title TEXT DEFAULT '',   -- Phase 9: first-class title (purpose or first heading)
    summary TEXT DEFAULT ''  -- Phase 9: first paragraph preview (≤220 chars)
    -- v2 additions (added via ALTER TABLE): corpus_class TEXT DEFAULT 'CORPUS_CLASS:DRAFT'; app_state TEXT DEFAULT 'inbox'
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

-- ══════════════════════════════════════════════════════════════════════════════
-- Phase 10 (Governance) — Authoring, Execution, Ollama, Policy, Audit
-- ══════════════════════════════════════════════════════════════════════════════

-- Document edits — transient drafts before saving to disk
CREATE TABLE IF NOT EXISTS doc_drafts (
    doc_id       TEXT    NOT NULL,
    body_text    TEXT    NOT NULL DEFAULT '',
    frontmatter_json TEXT NOT NULL DEFAULT '{}',
    title        TEXT    NOT NULL DEFAULT '',
    summary      TEXT    NOT NULL DEFAULT '',
    dirty        INTEGER NOT NULL DEFAULT 1,   -- 1=unsaved changes exist
    saved_ts     INTEGER,
    created_ts   INTEGER NOT NULL,
    UNIQUE(doc_id)
);
CREATE INDEX IF NOT EXISTS idx_doc_drafts_doc_id ON doc_drafts(doc_id);

-- Execution records — every code/shell block run
CREATE TABLE IF NOT EXISTS exec_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL UNIQUE,
    doc_id       TEXT    NOT NULL,
    block_id     TEXT    NOT NULL,
    executor     TEXT    NOT NULL,   -- 'human' | 'model:<name>' | 'system'
    language     TEXT    NOT NULL,   -- 'python' | 'shell'
    code_hash    TEXT    NOT NULL,
    exit_code    INTEGER,
    stdout       TEXT,
    stderr       TEXT,
    started_ts   INTEGER NOT NULL,
    finished_ts  INTEGER,
    status       TEXT    NOT NULL DEFAULT 'pending'  -- pending|running|success|error
);
CREATE INDEX IF NOT EXISTS idx_exec_runs_doc_id  ON exec_runs(doc_id);
CREATE INDEX IF NOT EXISTS idx_exec_runs_run_id  ON exec_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_exec_runs_status  ON exec_runs(status);

-- Execution artifacts — outputs attached to runs
CREATE TABLE IF NOT EXISTS exec_artifacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    artifact_id TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,   -- 'stdout' | 'file' | 'image' | 'json'
    content     TEXT,            -- inline text/JSON; NULL for binary
    path        TEXT,            -- on-disk path for large/binary
    size_bytes  INTEGER,
    created_ts  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_artifacts_run_id ON exec_artifacts(run_id);

-- LLM task invocations — every model call tracked
CREATE TABLE IF NOT EXISTS llm_invocations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    invocation_id  TEXT NOT NULL UNIQUE,
    task_type      TEXT NOT NULL,   -- summarize_doc | review_doc | generate_code | etc.
    model          TEXT NOT NULL,
    provider       TEXT NOT NULL DEFAULT 'ollama',
    doc_id         TEXT,            -- source doc if applicable
    scope_json     TEXT,            -- visible dirs/docs as JSON
    prompt_hash    TEXT NOT NULL,
    response_text  TEXT,
    response_json  TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    started_ts     INTEGER NOT NULL,
    finished_ts    INTEGER,
    error          TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_invocations_doc_id    ON llm_invocations(doc_id);
CREATE INDEX IF NOT EXISTS idx_llm_invocations_task_type ON llm_invocations(task_type);
CREATE INDEX IF NOT EXISTS idx_llm_invocations_status    ON llm_invocations(status);

-- Workspace policies — read/write/execute/propose/promote per entity
CREATE TABLE IF NOT EXISTS workspace_policies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace    TEXT NOT NULL,     -- directory path or logical name
    entity_type  TEXT NOT NULL,     -- 'human' | 'model' | 'system'
    entity_id    TEXT NOT NULL,     -- '*' for all, or specific id
    can_read     INTEGER NOT NULL DEFAULT 1,
    can_write    INTEGER NOT NULL DEFAULT 0,
    can_execute  INTEGER NOT NULL DEFAULT 0,
    can_propose  INTEGER NOT NULL DEFAULT 0,
    can_promote  INTEGER NOT NULL DEFAULT 0,  -- promote to canon (human-only by default)
    note         TEXT,
    created_ts   INTEGER NOT NULL,
    UNIQUE(workspace, entity_type, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_workspace_policies_workspace ON workspace_policies(workspace);
CREATE INDEX IF NOT EXISTS idx_workspace_policies_entity    ON workspace_policies(entity_type, entity_id);

-- Audit log — every significant action
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_ts     INTEGER NOT NULL,
    event_type   TEXT    NOT NULL,   -- index | edit | save | run | llm_call | promote | conflict
    actor_type   TEXT    NOT NULL,   -- 'human' | 'model' | 'system'
    actor_id     TEXT,
    doc_id       TEXT,
    run_id       TEXT,
    invocation_id TEXT,
    workspace    TEXT,
    detail       TEXT                 -- free JSON
);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_ts   ON audit_log(event_ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_doc_id     ON audit_log(doc_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);

-- System edges — DCNS extended for authority/flow beyond documents
CREATE TABLE IF NOT EXISTS system_edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type     TEXT NOT NULL,   -- 'doc' | 'workspace' | 'model' | 'tool' | 'role'
    source_id       TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    edge_type       TEXT NOT NULL,   -- may-read | may-write | may-execute | may-propose | promoted-to | derives-from | conflicts-with
    state           INTEGER,         -- +1|0|-1 trinary
    detail          TEXT,
    created_ts      INTEGER NOT NULL,
    UNIQUE(source_type, source_id, target_type, target_id, edge_type)
);
CREATE INDEX IF NOT EXISTS idx_system_edges_source ON system_edges(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_system_edges_target ON system_edges(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_system_edges_type   ON system_edges(edge_type);

-- System config table for UI-controlled settings (Ollama toggle, etc.)
CREATE TABLE IF NOT EXISTS system_config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_ts INTEGER NOT NULL
);
-- Default: Ollama disabled until user toggles on
INSERT OR IGNORE INTO system_config (key, value, updated_ts) VALUES ('ollama_enabled', 'false', 0);

-- ═══════════════════════════════════════════════════════════════════════════
-- Phase 15: Explicit Governance Workflow
-- ═══════════════════════════════════════════════════════════════════════════

-- Approval requests: every authority transfer must pass through here
-- before execution. No approval record = no state change allowed.
CREATE TABLE IF NOT EXISTS approval_requests (
    approval_id     TEXT    PRIMARY KEY,  -- apr-<uuid12>
    action_type     TEXT    NOT NULL,     -- canonical_promotion | edge_promotion |
                                          -- review_patch | supersede_operation
    doc_id          TEXT,                 -- primary document
    target_doc_id   TEXT,                 -- for supersede: replacement doc
    edge_id         INTEGER,              -- for edge_promotion
    from_state      TEXT    NOT NULL,
    to_state        TEXT    NOT NULL,
    requested_by    TEXT    NOT NULL,
    requested_ts    INTEGER NOT NULL,
    reason          TEXT    NOT NULL,
    diff_hash       TEXT,                 -- SHA-256 of content diff
    impact_summary  TEXT,                 -- JSON: affected downstream docs
    status          TEXT    NOT NULL DEFAULT 'pending',
                                          -- pending | approved | rejected | withdrawn
    reviewed_by     TEXT,
    reviewed_ts     INTEGER,
    review_note     TEXT,
    provenance_artifact_id TEXT           -- FK → provenance_artifacts.artifact_id
);
CREATE INDEX IF NOT EXISTS idx_apr_doc    ON approval_requests(doc_id);
CREATE INDEX IF NOT EXISTS idx_apr_status ON approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_apr_ts     ON approval_requests(requested_ts);

-- Provenance artifacts: immutable signed records of every approved authority event
CREATE TABLE IF NOT EXISTS provenance_artifacts (
    artifact_id     TEXT    PRIMARY KEY,  -- prv-<uuid12>
    approval_id     TEXT    NOT NULL,     -- FK → approval_requests
    action_type     TEXT    NOT NULL,
    document_id     TEXT    NOT NULL,
    from_state      TEXT    NOT NULL,
    to_state        TEXT    NOT NULL,
    approved_by     TEXT    NOT NULL,
    approved_at     INTEGER NOT NULL,     -- unix timestamp
    reason          TEXT    NOT NULL,
    diff_hash       TEXT,
    supersedes_id   TEXT,                 -- document_id superseded (if applicable)
    signature       TEXT    NOT NULL,     -- HMAC-SHA256 of canonical fields
    artifact_json   TEXT    NOT NULL      -- full immutable JSON record
);
CREATE INDEX IF NOT EXISTS idx_prv_doc ON provenance_artifacts(document_id);
CREATE INDEX IF NOT EXISTS idx_prv_apr ON provenance_artifacts(approval_id);

-- Edge approval requests: suggested → governed cross-project edges
CREATE TABLE IF NOT EXISTS edge_approval_requests (
    edge_apr_id     TEXT    PRIMARY KEY,  -- eap-<uuid12>
    source_doc_id   TEXT    NOT NULL,
    target_doc_id   TEXT    NOT NULL,
    edge_type       TEXT    NOT NULL,
    strength        REAL,
    proposed_authority TEXT NOT NULL DEFAULT 'suggested',
    cross_project   INTEGER NOT NULL DEFAULT 0,
    requested_by    TEXT    NOT NULL,
    requested_ts    INTEGER NOT NULL,
    reason          TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending',
    reviewed_by     TEXT,
    reviewed_ts     INTEGER,
    review_note     TEXT
);
CREATE INDEX IF NOT EXISTS idx_eap_source ON edge_approval_requests(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_eap_status ON edge_approval_requests(status);

-- Governance events: append-only constitutional record
CREATE TABLE IF NOT EXISTS governance_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_ts        INTEGER NOT NULL,
    event_type      TEXT    NOT NULL,     -- approval_request | approval_granted |
                                          -- approval_rejected | provenance_signed |
                                          -- edge_promoted | supersede_executed |
                                          -- rollback_triggered
    actor           TEXT    NOT NULL,
    doc_id          TEXT,
    approval_id     TEXT,
    artifact_id     TEXT,
    detail          TEXT                  -- JSON
);
CREATE INDEX IF NOT EXISTS idx_gev_doc  ON governance_events(doc_id);
CREATE INDEX IF NOT EXISTS idx_gev_ts   ON governance_events(event_ts);
CREATE INDEX IF NOT EXISTS idx_gev_type ON governance_events(event_type);

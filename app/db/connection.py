"""app/db/connection.py: Database connection and initialization for Bag of Holding v2.

Migrated from db.py (v0P). Logic unchanged.
Phase 4 additions:
  - lineage table initialized here (CREATE TABLE IF NOT EXISTS in schema.sql)
  - corpus_class index created after ALTER TABLE
  - schema_version stamped v2.1.0 for Phase 4
Phase 8 additions (Daenary + DCNS):
  - doc_coordinates table created (migration-safe)
  - doc_edges table created (migration-safe)
  - schema_version stamped v2.2.0
"""

import sqlite3
import os
import time
from pathlib import Path

DB_PATH = os.environ.get("BOH_DB", "boh.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()

    # Run base schema (idempotent via CREATE IF NOT EXISTS)
    # Strip the corpus_class index since the column may not exist yet
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    # Remove the corpus_class index line — applied after ALTER TABLE below
    schema_safe = "\n".join(
        line for line in schema.splitlines()
        if "idx_docs_corpus_class" not in line
    )
    conn.executescript(schema_safe)

    # v2 migration-safe column additions
    _add_column_if_missing(conn, "conflicts", "acknowledged", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "docs", "corpus_class", "TEXT DEFAULT 'CORPUS_CLASS:DRAFT'")
    # Phase 9: title + summary columns
    _add_column_if_missing(conn, "docs", "title",   "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "docs", "summary", "TEXT DEFAULT ''")

    # Phase 14: governed metadata contract columns. Existing documents are
    # backfilled by the indexer into Quarantine / Legacy Import if incomplete.
    _add_column_if_missing(conn, "docs", "project", "TEXT DEFAULT 'Quarantine / Legacy Import'")
    _add_column_if_missing(conn, "docs", "document_class", "TEXT DEFAULT 'legacy'")
    _add_column_if_missing(conn, "docs", "canonical_layer", "TEXT DEFAULT 'quarantine'")
    _add_column_if_missing(conn, "docs", "authority_state", "TEXT DEFAULT 'quarantined'")
    _add_column_if_missing(conn, "docs", "review_state", "TEXT DEFAULT 'unassigned'")
    _add_column_if_missing(conn, "docs", "provenance_json", "TEXT DEFAULT '{}'")
    _add_column_if_missing(conn, "docs", "source_hash", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "docs", "document_id", "TEXT DEFAULT ''")

    # Phase 14: governed metadata contract columns. Existing documents are
    # backfilled by the indexer into Quarantine / Legacy Import if incomplete.
    _add_column_if_missing(conn, "docs", "project", "TEXT DEFAULT 'Quarantine / Legacy Import'")
    _add_column_if_missing(conn, "docs", "document_class", "TEXT DEFAULT 'legacy'")
    _add_column_if_missing(conn, "docs", "canonical_layer", "TEXT DEFAULT 'quarantine'")
    _add_column_if_missing(conn, "docs", "authority_state", "TEXT DEFAULT 'quarantined'")
    _add_column_if_missing(conn, "docs", "review_state", "TEXT DEFAULT 'unassigned'")
    _add_column_if_missing(conn, "docs", "provenance_json", "TEXT DEFAULT '{}'")
    _add_column_if_missing(conn, "docs", "source_hash", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "docs", "document_id", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "docs", "app_state", "TEXT DEFAULT 'inbox'")
    # Phase 15: edge authority tracking
    _add_column_if_missing(conn, "doc_edges", "authority", "TEXT DEFAULT 'suggested'")
    _add_column_if_missing(conn, "doc_edges", "approved",  "INTEGER DEFAULT 0")

    # Phase 18: Daenary epistemic substrate columns
    _add_column_if_missing(conn, "docs", "epistemic_d",                 "INTEGER DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "epistemic_m",                 "TEXT DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "epistemic_q",                 "REAL DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "epistemic_c",                 "REAL DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "epistemic_correction_status", "TEXT DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "epistemic_valid_until",       "TEXT DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "epistemic_context_ref",       "TEXT DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "epistemic_source_ref",        "TEXT DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "epistemic_last_evaluated",    "TEXT DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "meaning_cost_json",           "TEXT DEFAULT NULL")
    _add_column_if_missing(conn, "docs", "custodian_review_state",      "TEXT DEFAULT NULL")
    # Phase 20.1: immutable certificate lineage for any canonical promotion
    _add_column_if_missing(conn, "docs", "promoted_by_certificate",     "TEXT DEFAULT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_epistemic_d ON docs(epistemic_d)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_custodian_state ON docs(custodian_review_state)")
    # Retrieval v1: stable chunk index for LLM context packs.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS doc_chunks (
            chunk_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            heading_path TEXT DEFAULT '',
            byte_start INTEGER NOT NULL DEFAULT 0,
            byte_end INTEGER NOT NULL DEFAULT 0,
            token_start INTEGER NOT NULL DEFAULT 0,
            token_end INTEGER NOT NULL DEFAULT 0,
            source_hash TEXT DEFAULT '',
            text_hash TEXT DEFAULT '',
            chunk_type TEXT NOT NULL DEFAULT 'body',
            text TEXT NOT NULL,
            lifecycle_state TEXT,
            authority_state TEXT,
            status TEXT,
            canonical_layer TEXT,
            metadata_json TEXT DEFAULT '{}',
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc_id ON doc_chunks(doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_chunks_path ON doc_chunks(path);
        CREATE INDEX IF NOT EXISTS idx_doc_chunks_type ON doc_chunks(chunk_type);
        CREATE INDEX IF NOT EXISTS idx_doc_chunks_authority ON doc_chunks(authority_state);
        CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_fts USING fts5(
            chunk_id UNINDEXED,
            doc_id UNINDEXED,
            heading_path,
            content
        );
        CREATE TABLE IF NOT EXISTS doc_chunk_embeddings (
            chunk_id TEXT PRIMARY KEY,
            embedding_model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            vector_json TEXT NOT NULL,
            text_hash TEXT DEFAULT '',
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_doc_chunk_embeddings_model ON doc_chunk_embeddings(embedding_model);
    """)
    # Phase 20: Constraint Lattice — Certificates and event log
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS certificates (
            certificate_id    TEXT PRIMARY KEY,
            node_id           TEXT NOT NULL,
            from_d            INTEGER NOT NULL,
            to_d              INTEGER NOT NULL,
            from_mode         TEXT,
            to_mode           TEXT,
            reason            TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            issuer_type       TEXT NOT NULL DEFAULT 'human',
            review_required   INTEGER NOT NULL DEFAULT 1,
            risk_class        TEXT NOT NULL DEFAULT 'moderate',
            cost_of_wrong     TEXT,
            q                 REAL NOT NULL,
            c                 REAL NOT NULL,
            valid_until       TEXT NOT NULL,
            context_ref       TEXT,
            created_at        TEXT NOT NULL,
            status            TEXT NOT NULL DEFAULT 'pending',
            reviewed_at       TEXT,
            reviewed_by       TEXT,
            review_note       TEXT,
            authority_plane   TEXT NOT NULL DEFAULT 'verification',
            plane_authority   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cert_node_id ON certificates(node_id);
        CREATE INDEX IF NOT EXISTS idx_cert_status  ON certificates(status);
        CREATE INDEX IF NOT EXISTS idx_cert_authority_plane ON certificates(authority_plane);

        CREATE TABLE IF NOT EXISTS lattice_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type      TEXT NOT NULL,
            certificate_id  TEXT,
            node_id         TEXT NOT NULL,
            from_d          INTEGER,
            to_d            INTEGER,
            from_mode       TEXT,
            to_mode         TEXT,
            reason          TEXT,
            detected_at     TEXT NOT NULL,
            severity        TEXT NOT NULL DEFAULT 'warning',
            detail_json     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_le_node_id ON lattice_events(node_id);
        CREATE INDEX IF NOT EXISTS idx_le_type    ON lattice_events(event_type);
    """)
    _add_column_if_missing(conn, "certificates", "authority_plane", "TEXT NOT NULL DEFAULT 'verification'")
    # Backfill legacy Phase 20 plane_authority values into the explicit Phase 20.1 field.
    try:
        conn.execute("UPDATE certificates SET authority_plane = lower(COALESCE(authority_plane, plane_authority, 'verification')) WHERE authority_plane IS NULL OR authority_plane = ''")
    except Exception:
        pass


    # Planar Storage bridge: passive plane registry and storage trace.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS planes (
            plane_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT DEFAULT '',
            mode_policy_json TEXT DEFAULT '{}',
            created_ts INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS storage_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            subject_type TEXT,
            subject_id TEXT,
            actor_id TEXT,
            plane TEXT,
            card_id TEXT,
            doc_id TEXT,
            detail_json TEXT DEFAULT '{}',
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_storage_events_type ON storage_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_storage_events_subject ON storage_events(subject_type, subject_id);
        CREATE INDEX IF NOT EXISTS idx_storage_events_card ON storage_events(card_id);
        CREATE INDEX IF NOT EXISTS idx_storage_events_doc ON storage_events(doc_id);
        CREATE INDEX IF NOT EXISTS idx_storage_events_created ON storage_events(created_ts);
    """)
    for plane_id, label, description in (
        ("informational", "Informational", "Source-derived claims and document-backed knowledge."),
        ("subjective", "Subjective", "LLM outputs, syntheses, nominations, and non-authoritative candidates."),
        ("canonical", "Canonical", "Accepted doctrine and certificate-gated canon."),
        ("evidence", "Evidence", "External evidence and source support."),
        ("internal", "Internal", "Workbench-local supporting material."),
        ("review", "Review", "Material awaiting explicit review."),
        ("conflict", "Conflict", "Known conflict or contradiction surface."),
        ("archive", "Archive", "Superseded, quarantined, or historical material."),
    ):
        conn.execute(
            "INSERT OR IGNORE INTO planes (plane_id, label, description, mode_policy_json, created_ts) VALUES (?,?,?,?,?)",
            (plane_id, label, description, "{}", int(time.time())),
        )

    # Phase 19: PCDS Plane Cards table
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cards (
            id               TEXT PRIMARY KEY,
            plane            TEXT NOT NULL,
            card_type        TEXT NOT NULL DEFAULT 'observation',
            topic            TEXT,
            b                INTEGER NOT NULL DEFAULT 0,
            d                INTEGER,
            m                TEXT,
            delta_json       TEXT DEFAULT '{}',
            constraints_json TEXT DEFAULT '{}',
            authority_json   TEXT DEFAULT '{}',
            observed_at      TEXT,
            valid_until      TEXT,
            context_ref_json TEXT DEFAULT '{}',
            payload_json     TEXT DEFAULT '{}',
            doc_id           TEXT,
            created_ts       INTEGER,
            updated_ts       INTEGER,
            plane_card_version INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_cards_plane    ON cards(plane);
        CREATE INDEX IF NOT EXISTS idx_cards_doc_id   ON cards(doc_id);
        CREATE INDEX IF NOT EXISTS idx_cards_d        ON cards(d);
        CREATE INDEX IF NOT EXISTS idx_cards_m        ON cards(m);
        CREATE INDEX IF NOT EXISTS idx_cards_valid    ON cards(valid_until);
        CREATE INDEX IF NOT EXISTS idx_cards_type     ON cards(card_type);
    """)
    conn.executescript("""
        CREATE VIEW IF NOT EXISTS plane_cards AS
        SELECT
            id AS card_id,
            id,
            plane,
            card_type,
            topic,
            b,
            d,
            m,
            delta_json,
            constraints_json,
            authority_json,
            observed_at,
            valid_until,
            context_ref_json,
            payload_json,
            doc_id,
            created_ts,
            updated_ts,
            plane_card_version
        FROM cards;
    """)
    # Phase 28.5: Planar Gate + Correction Ledger. Additive correction
    # memory only; these tables do not mutate gate rules or canon by themselves.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS planar_gate_results (
            gate_result_id TEXT PRIMARY KEY,
            context_pack_id TEXT NOT NULL,
            query TEXT DEFAULT '',
            operation TEXT NOT NULL DEFAULT 'answer_context',
            actor_id TEXT DEFAULT '',
            mode TEXT DEFAULT '',
            posture TEXT NOT NULL,
            blocking_reasons_json TEXT NOT NULL DEFAULT '[]',
            warning_reasons_json TEXT NOT NULL DEFAULT '[]',
            allowed_context_refs_json TEXT NOT NULL DEFAULT '[]',
            withheld_context_refs_json TEXT NOT NULL DEFAULT '[]',
            required_route TEXT,
            trace_event_type TEXT NOT NULL DEFAULT 'gate_passed',
            l6_proposal_allowed INTEGER NOT NULL DEFAULT 0,
            l6_proposal_types_json TEXT NOT NULL DEFAULT '[]',
            context_allowed_basis_json TEXT NOT NULL DEFAULT '{}',
            context_pack_json TEXT NOT NULL DEFAULT '{}',
            gate_result_json TEXT NOT NULL DEFAULT '{}',
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pgr_context ON planar_gate_results(context_pack_id);
        CREATE INDEX IF NOT EXISTS idx_pgr_posture ON planar_gate_results(posture);
        CREATE INDEX IF NOT EXISTS idx_pgr_created ON planar_gate_results(created_ts);

        CREATE TABLE IF NOT EXISTS planar_mistake_events (
            mistake_id TEXT PRIMARY KEY,
            detected_from TEXT NOT NULL,
            operation TEXT NOT NULL,
            actor_ref TEXT DEFAULT '',
            query_ref TEXT,
            context_pack_ref TEXT NOT NULL,
            expected_gate_result_ref TEXT,
            actual_gate_result_ref TEXT,
            mistake_class TEXT NOT NULL,
            impacted_refs_json TEXT NOT NULL DEFAULT '[]',
            severity TEXT NOT NULL DEFAULT 'medium',
            trace_event_ref TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pme_context ON planar_mistake_events(context_pack_ref);
        CREATE INDEX IF NOT EXISTS idx_pme_class ON planar_mistake_events(mistake_class);
        CREATE INDEX IF NOT EXISTS idx_pme_created ON planar_mistake_events(created_ts);

        CREATE TABLE IF NOT EXISTS planar_patch_proposals (
            patch_id TEXT PRIMARY KEY,
            proposed_from TEXT NOT NULL,
            proposal_type TEXT NOT NULL,
            proposed_change TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            blast_radius TEXT NOT NULL DEFAULT 'local',
            requires_review_by TEXT NOT NULL DEFAULT 'reviewer',
            status TEXT NOT NULL DEFAULT 'proposed',
            forbidden_auto_apply INTEGER NOT NULL DEFAULT 1,
            reviewed_by TEXT,
            reviewed_at INTEGER,
            review_note TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ppp_status ON planar_patch_proposals(status);
        CREATE INDEX IF NOT EXISTS idx_ppp_from ON planar_patch_proposals(proposed_from);
        CREATE INDEX IF NOT EXISTS idx_ppp_type ON planar_patch_proposals(proposal_type);

        CREATE TABLE IF NOT EXISTS planar_canon_change_records (
            canon_change_id TEXT PRIMARY KEY,
            patch_proposal_ref TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            approved_at INTEGER NOT NULL,
            changed_objects_json TEXT NOT NULL DEFAULT '[]',
            old_location_refs_json TEXT NOT NULL DEFAULT '[]',
            new_location_refs_json TEXT NOT NULL DEFAULT '[]',
            supersedes_refs_json TEXT NOT NULL DEFAULT '[]',
            migration_note TEXT NOT NULL DEFAULT '',
            regression_fixture_refs_json TEXT NOT NULL DEFAULT '[]',
            trace_event_ref TEXT,
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pcc_patch ON planar_canon_change_records(patch_proposal_ref);
        CREATE INDEX IF NOT EXISTS idx_pcc_approved ON planar_canon_change_records(approved_by);

        CREATE TABLE IF NOT EXISTS planar_information_residence_map (
            residence_id TEXT PRIMARY KEY,
            original_ref TEXT NOT NULL,
            current_ref TEXT NOT NULL,
            current_location TEXT NOT NULL,
            status TEXT NOT NULL,
            moved_by_event_ref TEXT,
            superseded_by TEXT,
            reason TEXT NOT NULL DEFAULT '',
            human_readable_locator TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pirm_original ON planar_information_residence_map(original_ref);
        CREATE INDEX IF NOT EXISTS idx_pirm_current ON planar_information_residence_map(current_ref);
        CREATE INDEX IF NOT EXISTS idx_pirm_status ON planar_information_residence_map(status);

        CREATE TABLE IF NOT EXISTS planar_fixture_cases (
            fixture_id TEXT PRIMARY KEY,
            fixture_pack_id TEXT NOT NULL,
            family TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT '',
            operation TEXT NOT NULL,
            actor_id TEXT NOT NULL DEFAULT '',
            fixture_json TEXT NOT NULL,
            expected_gate_result_json TEXT NOT NULL DEFAULT '{}',
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pfc_pack ON planar_fixture_cases(fixture_pack_id);
        CREATE INDEX IF NOT EXISTS idx_pfc_family ON planar_fixture_cases(family);
    """)

    # Phase 28: Actor, authority, responsibility, action ledger, attribution.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS actors (
            actor_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            source TEXT,
            external_ref TEXT,
            email TEXT,
            notes TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_actors_type ON actors(actor_type);
        CREATE INDEX IF NOT EXISTS idx_actors_active ON actors(active);

        CREATE TABLE IF NOT EXISTS actor_aliases (
            alias_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            source TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_actor_aliases_actor ON actor_aliases(actor_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_actor_aliases_alias ON actor_aliases(alias);

        CREATE TABLE IF NOT EXISTS actor_roles (
            role_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            role_name TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT,
            starts_at TEXT,
            ends_at TEXT,
            granted_by TEXT,
            authority_basis TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_actor_roles_actor ON actor_roles(actor_id);
        CREATE INDEX IF NOT EXISTS idx_actor_roles_scope ON actor_roles(scope_type, scope_id);

        CREATE TABLE IF NOT EXISTS authority_grants (
            grant_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT,
            authority_level TEXT NOT NULL,
            constraints_json TEXT,
            granted_by TEXT,
            starts_at TEXT,
            ends_at TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_authority_grants_actor ON authority_grants(actor_id);
        CREATE INDEX IF NOT EXISTS idx_authority_grants_action ON authority_grants(action);
        CREATE INDEX IF NOT EXISTS idx_authority_grants_scope ON authority_grants(scope_type, scope_id);

        CREATE TABLE IF NOT EXISTS responsibility_assignments (
            assignment_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            responsibility_type TEXT NOT NULL,
            scope_type TEXT,
            scope_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            assigned_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_resp_actor ON responsibility_assignments(actor_id);
        CREATE INDEX IF NOT EXISTS idx_resp_target ON responsibility_assignments(target_type, target_id);

        CREATE TABLE IF NOT EXISTS action_ledger (
            event_id TEXT PRIMARY KEY,
            actor_id TEXT,
            actor_type TEXT,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            project_id TEXT,
            authority_basis TEXT,
            authority_result TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            request_id TEXT,
            source_route TEXT,
            source_tool TEXT,
            ip_hint TEXT,
            user_agent_hint TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_action_ledger_actor ON action_ledger(actor_id);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_action ON action_ledger(action);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_target ON action_ledger(target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_created ON action_ledger(created_at);

        CREATE TABLE IF NOT EXISTS document_attribution (
            attribution_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            actor_id TEXT,
            attribution_type TEXT NOT NULL,
            confidence REAL,
            source TEXT,
            evidence_json TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_doc_attr_doc ON document_attribution(doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_attr_actor ON document_attribution(actor_id);
        CREATE INDEX IF NOT EXISTS idx_doc_attr_type ON document_attribution(attribution_type);

        CREATE TABLE IF NOT EXISTS contact_imports (
            import_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            summary_json TEXT,
            warnings_json TEXT
        );
    """)

    # Phase 28: Actor, authority, responsibility, action ledger, attribution.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS actors (
            actor_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            source TEXT,
            external_ref TEXT,
            email TEXT,
            notes TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_actors_type ON actors(actor_type);
        CREATE INDEX IF NOT EXISTS idx_actors_active ON actors(active);

        CREATE TABLE IF NOT EXISTS actor_aliases (
            alias_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            source TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_actor_aliases_actor ON actor_aliases(actor_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_actor_aliases_alias ON actor_aliases(alias);

        CREATE TABLE IF NOT EXISTS actor_roles (
            role_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            role_name TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT,
            starts_at TEXT,
            ends_at TEXT,
            granted_by TEXT,
            authority_basis TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_actor_roles_actor ON actor_roles(actor_id);
        CREATE INDEX IF NOT EXISTS idx_actor_roles_scope ON actor_roles(scope_type, scope_id);

        CREATE TABLE IF NOT EXISTS authority_grants (
            grant_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT,
            authority_level TEXT NOT NULL,
            constraints_json TEXT,
            granted_by TEXT,
            starts_at TEXT,
            ends_at TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_authority_grants_actor ON authority_grants(actor_id);
        CREATE INDEX IF NOT EXISTS idx_authority_grants_action ON authority_grants(action);
        CREATE INDEX IF NOT EXISTS idx_authority_grants_scope ON authority_grants(scope_type, scope_id);

        CREATE TABLE IF NOT EXISTS responsibility_assignments (
            assignment_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            responsibility_type TEXT NOT NULL,
            scope_type TEXT,
            scope_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            assigned_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_resp_actor ON responsibility_assignments(actor_id);
        CREATE INDEX IF NOT EXISTS idx_resp_target ON responsibility_assignments(target_type, target_id);

        CREATE TABLE IF NOT EXISTS action_ledger (
            event_id TEXT PRIMARY KEY,
            actor_id TEXT,
            actor_type TEXT,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            project_id TEXT,
            authority_basis TEXT,
            authority_result TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            request_id TEXT,
            source_route TEXT,
            source_tool TEXT,
            ip_hint TEXT,
            user_agent_hint TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_action_ledger_actor ON action_ledger(actor_id);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_action ON action_ledger(action);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_target ON action_ledger(target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_created ON action_ledger(created_at);

        CREATE TABLE IF NOT EXISTS document_attribution (
            attribution_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            actor_id TEXT,
            attribution_type TEXT NOT NULL,
            confidence REAL,
            source TEXT,
            evidence_json TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_doc_attr_doc ON document_attribution(doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_attr_actor ON document_attribution(actor_id);
        CREATE INDEX IF NOT EXISTS idx_doc_attr_type ON document_attribution(attribution_type);

        CREATE TABLE IF NOT EXISTS contact_imports (
            import_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            summary_json TEXT,
            warnings_json TEXT
        );
    """)


    # Phase 21: Plane Interfaces — explicit cross-plane translation artifacts
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS plane_interfaces (
            interface_id          TEXT PRIMARY KEY,
            source_plane          TEXT NOT NULL,
            target_plane          TEXT NOT NULL,
            translation_reason    TEXT NOT NULL,
            loss_notes_json       TEXT NOT NULL DEFAULT '[]',
            certificate_refs_json TEXT NOT NULL DEFAULT '[]',
            q_delta               REAL NOT NULL DEFAULT 0,
            c_delta               REAL NOT NULL DEFAULT 0,
            authority_plane       TEXT NOT NULL DEFAULT 'verification',
            created_at            TEXT NOT NULL,
            node_id               TEXT,
            created_by            TEXT,
            status                TEXT NOT NULL DEFAULT 'active',
            metadata_json         TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_pi_node_id ON plane_interfaces(node_id);
        CREATE INDEX IF NOT EXISTS idx_pi_source_target ON plane_interfaces(source_plane, target_plane);
        CREATE INDEX IF NOT EXISTS idx_pi_authority_plane ON plane_interfaces(authority_plane);
        CREATE INDEX IF NOT EXISTS idx_pi_created_at ON plane_interfaces(created_at);
    """)
    # Phase 22: Constraint-native graph + flow traversal
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS lattice_edges (
            edge_id       TEXT PRIMARY KEY,
            source_id     TEXT NOT NULL,
            target_id     TEXT NOT NULL,
            relation      TEXT NOT NULL,
            weight        REAL NOT NULL DEFAULT 1.0,
            status        TEXT NOT NULL DEFAULT 'active',
            created_at    TEXT NOT NULL,
            created_by    TEXT NOT NULL DEFAULT 'human',
            reversible    INTEGER NOT NULL DEFAULT 1,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_lattice_edges_source ON lattice_edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_lattice_edges_target ON lattice_edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_lattice_edges_relation ON lattice_edges(relation);
        CREATE INDEX IF NOT EXISTS idx_lattice_edges_status ON lattice_edges(status);
    """)
    # Phase 23: Feedback Rewrite Engine — outcomes rewrite lattice topology
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS feedback_rewrites (
            rewrite_id           TEXT PRIMARY KEY,
            feedback_kind        TEXT NOT NULL,
            action               TEXT NOT NULL,
            reason               TEXT NOT NULL,
            actor                TEXT NOT NULL,
            edge_id              TEXT,
            node_id              TEXT,
            previous_state_json  TEXT NOT NULL DEFAULT '{}',
            new_state_json       TEXT NOT NULL DEFAULT '{}',
            reversible           INTEGER NOT NULL DEFAULT 1,
            reverted             INTEGER NOT NULL DEFAULT 0,
            created_at           TEXT NOT NULL,
            metadata_json        TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_rewrites_edge ON feedback_rewrites(edge_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_rewrites_node ON feedback_rewrites(node_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_rewrites_action ON feedback_rewrites(action);
        CREATE INDEX IF NOT EXISTS idx_feedback_rewrites_kind ON feedback_rewrites(feedback_kind);
        CREATE INDEX IF NOT EXISTS idx_feedback_rewrites_reverted ON feedback_rewrites(reverted);
    """)


    # Phase 24: Coherence Decay + Refresh Engine — time-bound truth validity
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS coherence_refresh_events (
            refresh_id          TEXT PRIMARY KEY,
            node_id             TEXT NOT NULL,
            refresh_type        TEXT NOT NULL DEFAULT 'review',
            amount              REAL NOT NULL DEFAULT 0.0,
            reason              TEXT NOT NULL,
            actor               TEXT NOT NULL,
            created_at          TEXT NOT NULL,
            evidence_refs_json  TEXT NOT NULL DEFAULT '[]',
            metadata_json       TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_coherence_refresh_node ON coherence_refresh_events(node_id);
        CREATE INDEX IF NOT EXISTS idx_coherence_refresh_created ON coherence_refresh_events(created_at);

        CREATE TABLE IF NOT EXISTS coherence_scores (
            node_id            TEXT PRIMARY KEY,
            coherence          REAL NOT NULL,
            c0                 REAL NOT NULL,
            k                  REAL NOT NULL,
            tau_days           REAL NOT NULL,
            refresh_credit     REAL NOT NULL,
            decay_state        TEXT NOT NULL,
            refresh_required   INTEGER NOT NULL DEFAULT 0,
            priority           TEXT NOT NULL DEFAULT 'none',
            reason             TEXT NOT NULL,
            evaluated_at       TEXT NOT NULL,
            valid_until        TEXT,
            score_json         TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_coherence_scores_state ON coherence_scores(decay_state);
        CREATE INDEX IF NOT EXISTS idx_coherence_scores_refresh ON coherence_scores(refresh_required);
        CREATE INDEX IF NOT EXISTS idx_coherence_scores_priority ON coherence_scores(priority);
    """)

    # Phase 24.2: Temporal Coherence Governor
    # Strict migration order: anchor_events (re-anchor audit) -> open_items (registry)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS anchor_events (
            anchor_id              TEXT PRIMARY KEY,
            node_id                TEXT NOT NULL,
            triggered_by           TEXT NOT NULL,
            trigger_reason         TEXT NOT NULL,
            drift_risk_at_trigger  TEXT NOT NULL DEFAULT 'high',
            forced_d               INTEGER NOT NULL DEFAULT 0,
            forced_m               TEXT NOT NULL DEFAULT 'contain',
            active_plane           TEXT,
            trinary_json           TEXT NOT NULL DEFAULT '{}',
            status                 TEXT NOT NULL DEFAULT 'active',
            created_at             TEXT NOT NULL,
            resolved_at            TEXT,
            metadata_json          TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_anchor_node ON anchor_events(node_id);
        CREATE INDEX IF NOT EXISTS idx_anchor_status ON anchor_events(status);
        CREATE INDEX IF NOT EXISTS idx_anchor_created ON anchor_events(created_at);

        CREATE TABLE IF NOT EXISTS open_items (
            id                   TEXT PRIMARY KEY,
            plane_boundary       TEXT NOT NULL,
            created_at           TEXT NOT NULL,
            valid_until          TEXT,
            resolution_authority TEXT NOT NULL,
            status               TEXT NOT NULL DEFAULT 'open',
            drift_priority       TEXT NOT NULL DEFAULT 'moderate',
            node_id              TEXT,
            description          TEXT NOT NULL DEFAULT '',
            context_ref_json     TEXT NOT NULL DEFAULT '{}',
            resolved_at          TEXT,
            resolved_by          TEXT,
            metadata_json        TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_open_items_status ON open_items(status);
        CREATE INDEX IF NOT EXISTS idx_open_items_priority ON open_items(drift_priority);
        CREATE INDEX IF NOT EXISTS idx_open_items_node ON open_items(node_id);
        CREATE INDEX IF NOT EXISTS idx_open_items_created ON open_items(created_at);
    """)


    # Phase 24.3: Authority Enforcement — Fix A + Fix B
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS authority_resolution_log (
            id                    TEXT PRIMARY KEY,
            target_id             TEXT NOT NULL,
            target_type           TEXT NOT NULL DEFAULT 'open_item',
            actor_id              TEXT NOT NULL,
            actor_role            TEXT NOT NULL DEFAULT '',
            actor_team            TEXT NOT NULL DEFAULT '',
            required_authority    TEXT NOT NULL,
            authorization_result  INTEGER NOT NULL DEFAULT 0,
            failure_reason        TEXT NOT NULL DEFAULT '',
            timestamp             TEXT NOT NULL,
            metadata_json         TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_arl_target ON authority_resolution_log(target_id);
        CREATE INDEX IF NOT EXISTS idx_arl_actor ON authority_resolution_log(actor_id);
        CREATE INDEX IF NOT EXISTS idx_arl_result ON authority_resolution_log(authorization_result);

        CREATE TABLE IF NOT EXISTS authority_promotions (
            promotion_id       TEXT PRIMARY KEY,
            old_authority      TEXT NOT NULL,
            new_authority      TEXT NOT NULL,
            promotion_reason   TEXT NOT NULL,
            approved_by        TEXT NOT NULL,
            target_id          TEXT,
            target_type        TEXT,
            promotion_timestamp TEXT NOT NULL,
            lineage_ref        TEXT,
            metadata_json      TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_ap_target ON authority_promotions(target_id);
        CREATE INDEX IF NOT EXISTS idx_ap_approved ON authority_promotions(approved_by);
    """)

    # Phase 24.3: Temporal Escalation — Fix C + Fix D
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS escalation_registry (
            plane                        TEXT NOT NULL,
            severity                     TEXT NOT NULL,
            owner                        TEXT NOT NULL,
            supervisor                   TEXT NOT NULL,
            max_resolution_window_hours  INTEGER NOT NULL DEFAULT 48,
            promotion_rule               TEXT NOT NULL DEFAULT '',
            containment_required         INTEGER NOT NULL DEFAULT 1,
            updated_at                   TEXT NOT NULL,
            metadata_json                TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (plane, severity)
        );

        CREATE TABLE IF NOT EXISTS escalation_events (
            escalation_id          TEXT PRIMARY KEY,
            node_id                TEXT NOT NULL,
            drift_risk             TEXT NOT NULL,
            escalation_level       TEXT NOT NULL,
            action_taken           TEXT NOT NULL DEFAULT '',
            notification_sent      INTEGER NOT NULL DEFAULT 0,
            owner                  TEXT,
            supervisor             TEXT,
            refresh_due            TEXT,
            escalated_to           TEXT,
            why                    TEXT,
            supervisory_plane      TEXT,
            forced_scope_reduction INTEGER NOT NULL DEFAULT 0,
            anchor_id              TEXT,
            route_found            INTEGER NOT NULL DEFAULT 0,
            created_at             TEXT NOT NULL,
            metadata_json          TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_esc_node ON escalation_events(node_id);
        CREATE INDEX IF NOT EXISTS idx_esc_level ON escalation_events(escalation_level);
        CREATE INDEX IF NOT EXISTS idx_esc_created ON escalation_events(created_at);

        CREATE TABLE IF NOT EXISTS canonical_locks (
            lock_id          TEXT PRIMARY KEY,
            node_id          TEXT NOT NULL,
            reason           TEXT NOT NULL,
            escalation_id    TEXT,
            active           INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT NOT NULL,
            released_at      TEXT,
            metadata_json    TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_cl_node ON canonical_locks(node_id);
        CREATE INDEX IF NOT EXISTS idx_cl_active ON canonical_locks(active);
    """)

    # Phase 25: Substrate Lattice — Fix G
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS substrate_lattice_registry (
            lattice_id             TEXT PRIMARY KEY,
            domain                 TEXT NOT NULL,
            label                  TEXT NOT NULL,
            k_physical             TEXT NOT NULL DEFAULT '',
            k_informational        TEXT NOT NULL DEFAULT '',
            k_subjective           TEXT NOT NULL DEFAULT '',
            x_physical             TEXT NOT NULL DEFAULT '',
            x_informational        TEXT NOT NULL DEFAULT '',
            x_subjective           TEXT NOT NULL DEFAULT '',
            f_physical             TEXT NOT NULL DEFAULT '',
            f_informational        TEXT NOT NULL DEFAULT '',
            f_subjective           TEXT NOT NULL DEFAULT '',
            cpl_json               TEXT NOT NULL DEFAULT '{}',
            proj_json              TEXT NOT NULL DEFAULT '{}',
            obs_json               TEXT NOT NULL DEFAULT '{}',
            requires_new_ontology  INTEGER NOT NULL DEFAULT 0,
            validation_notes       TEXT NOT NULL DEFAULT '',
            created_at             TEXT NOT NULL,
            metadata_json          TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_sl_domain ON substrate_lattice_registry(domain);
        CREATE INDEX IF NOT EXISTS idx_sl_new_onto ON substrate_lattice_registry(requires_new_ontology);
    """)


    # Now safe to create the corpus_class index

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_docs_corpus_class ON docs(corpus_class)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_project ON docs(project)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_document_class ON docs(document_class)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_canonical_layer ON docs(canonical_layer)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_authority_state ON docs(authority_state)")

    # Phase 8: doc_coordinates and doc_edges tables (created via schema.sql IF NOT EXISTS —
    # but we also call executescript with the full schema so this is already handled above;
    # repeat explicitly here so existing databases get them via migration too).
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS doc_coordinates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id          TEXT    NOT NULL,
            dimension       TEXT    NOT NULL,
            state           INTEGER NOT NULL,
            quality         REAL,
            confidence      REAL,
            mode            TEXT,
            observed_ts     INTEGER,
            valid_until_ts  INTEGER,
            source          TEXT    DEFAULT 'frontmatter',
            UNIQUE(doc_id, dimension)
        );
        CREATE INDEX IF NOT EXISTS idx_doc_coordinates_doc_id      ON doc_coordinates(doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_coordinates_dimension   ON doc_coordinates(dimension);
        CREATE INDEX IF NOT EXISTS idx_doc_coordinates_state       ON doc_coordinates(state);
        CREATE INDEX IF NOT EXISTS idx_doc_coordinates_valid_until ON doc_coordinates(valid_until_ts);

        CREATE TABLE IF NOT EXISTS doc_edges (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_doc_id   TEXT    NOT NULL,
            target_doc_id   TEXT    NOT NULL,
            edge_type       TEXT    NOT NULL,
            state           INTEGER,
            permeability    REAL,
            load_score      REAL,
            detected_ts     INTEGER NOT NULL,
            detail          TEXT,
            UNIQUE(source_doc_id, target_doc_id, edge_type)
        );
        CREATE INDEX IF NOT EXISTS idx_doc_edges_source ON doc_edges(source_doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_edges_target ON doc_edges(target_doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_edges_type   ON doc_edges(edge_type);
    """)

    # schema_version table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT NOT NULL,
            applied_ts INTEGER NOT NULL
        )
    """)
    for ver in ("v2.0.0", "v2.1.0", "v2.2.0", "v2.3.0", "v2.4.0", "v2.5.0-phase14"):
        existing = conn.execute(
            "SELECT version FROM schema_version WHERE version = ?", (ver,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO schema_version (version, applied_ts) VALUES (?, ?)",
                (ver, int(time.time())),
            )

    # Phase 26C — SC3 constitutive violations audit table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sc3_violations (
            violation_id  TEXT PRIMARY KEY,
            action        TEXT NOT NULL,
            node_id       TEXT NOT NULL,
            source_plane  TEXT NOT NULL,
            target_plane  TEXT NOT NULL,
            requested_by  TEXT NOT NULL,
            required_resolver TEXT NOT NULL,
            severity      TEXT NOT NULL,
            explanation   TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sc3v_action ON sc3_violations(action)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sc3v_node ON sc3_violations(node_id)")

    for ver in ("v2.6.0-phase26",):
        existing = conn.execute(
            "SELECT version FROM schema_version WHERE version = ?", (ver,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO schema_version (version, applied_ts) VALUES (?, ?)",
                (ver, int(time.time())),
            )

    # Planar Background Services: intake layer persistence tables (Phase 7).
    # All tables are additive; no existing tables are modified.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS intake_capabilities (
            intake_capability_id  TEXT PRIMARY KEY,
            source_ref            TEXT NOT NULL,
            batch_id              TEXT NOT NULL,
            discovered            INTEGER NOT NULL DEFAULT 1,
            preservable           INTEGER NOT NULL DEFAULT 0,
            normalizable          INTEGER NOT NULL DEFAULT 0,
            interpretable         INTEGER NOT NULL DEFAULT 0,
            queryable             INTEGER NOT NULL DEFAULT 0,
            canon_eligible        INTEGER NOT NULL DEFAULT 0,
            required_adapter      TEXT,
            safety_lane           TEXT NOT NULL DEFAULT 'hold',
            failure_reason        TEXT,
            lifecycle_state       TEXT NOT NULL DEFAULT 'discovered',
            trust_state           TEXT NOT NULL DEFAULT 'unknown',
            authority_default     TEXT NOT NULL DEFAULT 'none',
            trace_event_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at            TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ic_batch ON intake_capabilities(batch_id);
        CREATE INDEX IF NOT EXISTS idx_ic_safety_lane ON intake_capabilities(safety_lane);
        CREATE INDEX IF NOT EXISTS idx_ic_lifecycle ON intake_capabilities(lifecycle_state);
        CREATE INDEX IF NOT EXISTS idx_ic_source ON intake_capabilities(source_ref);

        CREATE TABLE IF NOT EXISTS intake_raw_artifacts (
            raw_artifact_id       TEXT PRIMARY KEY,
            intake_capability_id  TEXT NOT NULL,
            source_ref            TEXT NOT NULL,
            batch_id              TEXT NOT NULL,
            source_hash_sha256    TEXT NOT NULL,
            preserved_hash_sha256 TEXT NOT NULL,
            byte_size             INTEGER NOT NULL,
            preservation_path     TEXT NOT NULL,
            media_type            TEXT,
            created_at            TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ira_cap ON intake_raw_artifacts(intake_capability_id);
        CREATE INDEX IF NOT EXISTS idx_ira_batch ON intake_raw_artifacts(batch_id);
        CREATE INDEX IF NOT EXISTS idx_ira_hash ON intake_raw_artifacts(source_hash_sha256);

        CREATE TABLE IF NOT EXISTS intake_normalized_artifacts (
            normalized_artifact_id TEXT PRIMARY KEY,
            raw_artifact_id        TEXT NOT NULL,
            adapter_run_id         TEXT NOT NULL,
            output_path            TEXT NOT NULL,
            output_hash_sha256     TEXT NOT NULL,
            output_type            TEXT NOT NULL,
            known_losses_json      TEXT NOT NULL DEFAULT '[]',
            warnings_json          TEXT NOT NULL DEFAULT '[]',
            created_at             TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ina_raw ON intake_normalized_artifacts(raw_artifact_id);
        CREATE INDEX IF NOT EXISTS idx_ina_adapter_run ON intake_normalized_artifacts(adapter_run_id);

        CREATE TABLE IF NOT EXISTS intake_adapter_runs (
            adapter_run_id        TEXT PRIMARY KEY,
            adapter_id            TEXT NOT NULL,
            adapter_version       TEXT NOT NULL,
            raw_artifact_id       TEXT NOT NULL,
            intake_capability_id  TEXT NOT NULL,
            success               INTEGER NOT NULL DEFAULT 0,
            failure_reason        TEXT,
            warnings_json         TEXT NOT NULL DEFAULT '[]',
            output_artifact_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at            TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_iar_capability ON intake_adapter_runs(intake_capability_id);
        CREATE INDEX IF NOT EXISTS idx_iar_adapter ON intake_adapter_runs(adapter_id);

        CREATE TABLE IF NOT EXISTS intake_quarantine_records (
            quarantine_record_id   TEXT PRIMARY KEY,
            intake_capability_id   TEXT NOT NULL,
            quarantine_reason      TEXT NOT NULL,
            quarantine_category    TEXT NOT NULL,
            review_required        INTEGER NOT NULL DEFAULT 1,
            created_at             TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_iqr_capability ON intake_quarantine_records(intake_capability_id);
        CREATE INDEX IF NOT EXISTS idx_iqr_category ON intake_quarantine_records(quarantine_category);

        CREATE TABLE IF NOT EXISTS intake_trace_events (
            trace_event_id        TEXT PRIMARY KEY,
            event_type            TEXT NOT NULL,
            intake_capability_id  TEXT,
            job_id                TEXT,
            detail_json           TEXT NOT NULL DEFAULT '{}',
            created_at            TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ite_capability ON intake_trace_events(intake_capability_id);
        CREATE INDEX IF NOT EXISTS idx_ite_event_type ON intake_trace_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_ite_created ON intake_trace_events(created_at);
    """)

    ver = "v2.7.0-phase-intake"
    existing = conn.execute(
        "SELECT version FROM schema_version WHERE version = ?", (ver,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO schema_version (version, applied_ts) VALUES (?, ?)",
            (ver, int(time.time())),
        )

    conn.commit()
    conn.close()

    # The committed schema above is the immutable BASELINE. The migration runner stamps it
    # (once) in schema_migrations and applies any forward migrations on the same DB. Kept
    # after the commit so the on-disk DB is consistent before any forward migration/backup.
    # Imported lazily to avoid a circular import.
    from app.db import migrations as _migrations
    _migrations.run_migrations(get_conn, DB_PATH)


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, col_def: str):
    """Safely add a column to a table if it does not already exist."""
    existing_cols = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing_cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def fetchall(query: str, params=()) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetchone(query: str, params=()) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def execute(query: str, params=()):
    conn = get_conn()
    try:
        conn.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def executemany(query: str, params_list: list):
    conn = get_conn()
    try:
        conn.executemany(query, params_list)
        conn.commit()
    finally:
        conn.close()

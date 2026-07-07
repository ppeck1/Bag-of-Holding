"""Forward migration 0002 — intake→retrieval promotion ledgers (WO-2).

STATUS: SCHEMA-APPROVED (owner review 2026-06-10, DEC-0004) and REGISTERED in
`app.db.migrations.MIGRATIONS` for temp-clone rehearsal. **Application to the real `boh.db`,
real-database rehearsal, and the promotion runtime remain separately gated and NOT authorized.**
Review package (incl. the lineage-enforcement matrix) and the WO-2 proposal (owner
refinements 1–4) are kept in the private working repository's internal records.
Doctrine: decision records DEC-0003 (artifact identity deduplicates across fingerprint eras) and
DEC-0004 (0002 schema decisions: `.py`→`text` accepted; `html_neutralized_markdown` carried by the
dedicated `normalized_output_profile` ledger column, never by core artifact `output_type`;
`intake_run_id` approved; authority tier advisory-metadata-only; `promotion_batch_id` nullable
grouping metadata only).

Design notes (for owner review):

- `intake_handoffs` is the DURABLE promotability source of truth (proposal refinement 1). Today a
  `HandoffPacket` is transient and only a trace event records the handoff; promotion eligibility
  must never be derived from trace-event scans. One row per handoff event; later reassessments
  append new rows (no UNIQUE on capability), latest-by-`created_at` wins. Per DEC-0003 the row
  carries the FULL provenance bridge: the (possibly re-mint-era) `intake_capability_id`, its
  `intake_run_id` and `source_revision_id`, AND the (possibly earlier-era, content-identical)
  `normalized_artifact_id` it resolves to. `intake_run_id` is an addition beyond the proposal's
  column list, required by DEC-0003's capability → run → source-revision chain — flagged for
  explicit owner approval in the review package.

- `intake_promotions` is the promotion ledger (proposal §1, owner-amended shape). Identity /
  idempotency: at most ONE 'active' promotion per `source_revision_id`, enforced by a PARTIAL
  UNIQUE INDEX — this is the single-winner concurrency boundary for concurrent operator requests
  (analogous to WO-1's claim lease). Re-promoting an unchanged revision is a no-op returning the
  existing `doc_id`; a changed revision is a NEW revision id (WO-1 `srid-v1`), so it gets its own
  row and `supersedes_promotion_id` marks the lineage. `status` ∈ active | superseded | demoted.
  Demotion is reversible bookkeeping: `demoted_by`/`demoted_at` all-or-none (CHECK), and
  `status='demoted'` iff `demoted_at` is set (CHECK). Adapter + policy snapshots are carried so
  retrieval provenance can explain WHICH transformation contract produced the normalized artifact
  (refinement 3). `normalized_output_type` is the AUTHORITATIVE format (refinement 2 — never
  inferred from the always-`.md` filename).

- FK posture (owner-directed lineage-enforcement review, 2026-06-10): SQLite FKs are declared for
  every reference whose PARENT is migration-managed — `intake_source_revisions` (0001),
  `intake_runs` (0001), `intake_handoffs` (this migration), and the `supersedes_promotion_id`
  self-reference. References to `intake_capabilities` / `intake_normalized_artifacts` / `docs`
  remain deliberately FK-free: those parents live in the non-migration-managed baseline/Phase-7
  layer whose lifecycle is outside the migration ledger; their validity is enforced by
  transactional application validation at write time plus dangling-reference detection queries
  exercised by the gate tests (full matrix in the review package §2b). Enforcement of declared FKs
  requires `PRAGMA foreign_keys=ON` (orchestrator/test concern, as with 0001). No triggers — all
  invariants are declarative (CHECK/UNIQUE/FK) or owned by the promotion service code.

- Plain `CREATE TABLE`/`CREATE INDEX` (no `IF NOT EXISTS`): fail loudly on unexpected pre-existing
  shape; idempotency comes from the `schema_migrations` ledger.

The runner wraps `up(conn)` in one BEGIN/COMMIT and owns the ledger insert; `up` must NOT commit.
"""

from __future__ import annotations

import sqlite3

from app.db.migrations import Migration


def _up(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE intake_handoffs (
            handoff_id                TEXT PRIMARY KEY,
            intake_capability_id      TEXT NOT NULL,
            intake_run_id             TEXT NOT NULL,
            source_revision_id        TEXT NOT NULL,
            normalized_artifact_id    TEXT NOT NULL,
            handoff_ready             INTEGER NOT NULL CHECK (handoff_ready IN (0, 1)),
            handoff_at                TEXT NOT NULL,
            adapter_id                TEXT NOT NULL,
            adapter_version           TEXT NOT NULL,
            adapter_registry_version  TEXT NOT NULL,
            policy_snapshot_hash      TEXT NOT NULL,
            normalized_output_type    TEXT NOT NULL,
            normalized_output_profile TEXT,
            warnings_json             TEXT NOT NULL DEFAULT '[]',
            created_at                TEXT NOT NULL,
            FOREIGN KEY (source_revision_id)
                REFERENCES intake_source_revisions (source_revision_id),
            FOREIGN KEY (intake_run_id)
                REFERENCES intake_runs (run_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_intake_handoffs_capability "
        "ON intake_handoffs (intake_capability_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX idx_intake_handoffs_revision "
        "ON intake_handoffs (source_revision_id, created_at DESC)"
    )
    # Promotability listing: ready handoffs in arrival order.
    conn.execute(
        "CREATE INDEX idx_intake_handoffs_ready_created "
        "ON intake_handoffs (handoff_ready, created_at)"
    )

    conn.execute(
        """
        CREATE TABLE intake_promotions (
            promotion_id              TEXT PRIMARY KEY,
            promotion_batch_id        TEXT,
            source_revision_id        TEXT NOT NULL,
            intake_capability_id      TEXT NOT NULL,
            handoff_id                TEXT NOT NULL,
            normalized_artifact_id    TEXT NOT NULL,
            doc_id                    TEXT NOT NULL,
            normalized_hash           TEXT NOT NULL,
            normalized_output_type    TEXT NOT NULL,
            normalized_output_profile TEXT,
            adapter_id                TEXT NOT NULL,
            adapter_version           TEXT NOT NULL,
            adapter_registry_version  TEXT NOT NULL,
            policy_snapshot_hash      TEXT NOT NULL,
            status                    TEXT NOT NULL CHECK (
                status IN ('active', 'superseded', 'demoted')
            ),
            supersedes_promotion_id   TEXT,
            promoted_by               TEXT NOT NULL,
            promoted_at               TEXT NOT NULL,
            demoted_by                TEXT,
            demoted_at                TEXT,
            updated_at                TEXT NOT NULL,
            FOREIGN KEY (source_revision_id)
                REFERENCES intake_source_revisions (source_revision_id),
            FOREIGN KEY (handoff_id)
                REFERENCES intake_handoffs (handoff_id),
            FOREIGN KEY (supersedes_promotion_id)
                REFERENCES intake_promotions (promotion_id),
            CHECK (
                (demoted_by IS NULL AND demoted_at IS NULL)
                OR (demoted_by IS NOT NULL AND demoted_at IS NOT NULL)
            ),
            CHECK ((status = 'demoted') = (demoted_at IS NOT NULL))
        )
        """
    )
    # Single-winner idempotency boundary: at most ONE active promotion per source revision.
    conn.execute(
        "CREATE UNIQUE INDEX idx_intake_promotions_active_revision "
        "ON intake_promotions (source_revision_id) WHERE status = 'active'"
    )
    # Demotion scoping + retrieval-side provenance resolution.
    conn.execute(
        "CREATE INDEX idx_intake_promotions_doc "
        "ON intake_promotions (doc_id)"
    )
    conn.execute(
        "CREATE INDEX idx_intake_promotions_status_promoted "
        "ON intake_promotions (status, promoted_at)"
    )
    conn.execute(
        "CREATE INDEX idx_intake_promotions_handoff "
        "ON intake_promotions (handoff_id)"
    )


MIGRATION = Migration(
    id="0002_intake_retrieval_promotion",
    description=(
        "Add intake_handoffs (durable promotability source of truth, DEC-0003 provenance bridge) "
        "+ intake_promotions (reversible, single-active-winner promotion ledger) for the governed "
        "intake->retrieval bridge."
    ),
    up=_up,
)

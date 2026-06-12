"""Forward migration 0001 — intake orchestration integrity ledgers.

STATUS: REGISTERED in `app.db.migrations.MIGRATIONS` and APPLIED. It runs via the
`schema_migrations` ledger during `init_db()`, and was applied to the production `boh.db` in
Gate C2 (2026-06-04). `init_db()`/`schema.sql` are not edited — these tables are added through
the forward-migration path only.

Design notes (owner-reviewed):

- `intake_source_revisions` is the idempotency state machine. Identity (UNIQUE) is REVISION
  identity — `canonical_source_ref + source_hash_sha256 + policy_snapshot_hash +
  adapter_registry_version` — all NOT NULL (SQLite allows multiple NULLs in a UNIQUE key, which
  would undermine dedup). `lifecycle_state` is mutable, never identity. Concurrency is resolved
  by an ATOMIC CLAIM LEASE: the scheduler claims a row via one conditional UPDATE
  (`WHERE lifecycle_state='discovered' AND claim_token IS NULL`) and dispatches only when
  exactly one row changed. The four claim fields are all-or-none (a CHECK constraint) and
  `claim_token` is UNIQUE (NULLs allowed for unclaimed rows) so accidental token reuse fails
  loudly. An expired lease is reconciled to `failed` with a structured code
  (e.g. `stale_claim_after_restart`) and requires explicit replay — it never auto-loops.
  `last_seen_at` records repeated observation of an unchanged source WITHOUT creating new work.

- `intake_runs` is the durable per-attempt ledger and the authoritative record for unexpected
  failures, including exceptions BEFORE a capability/revision exists (`intake_capability_id` and
  `source_revision_id` nullable). `source_ref_snapshot` preserves which source a pre-revision
  failure came from. `failure_code` (structured) is split from `failure_detail` (human-readable).
  `started_at`/`finished_at` capture wait-vs-run timing separately from `created_at`/`updated_at`.

- `last_run_id` is intentionally OMITTED from the revision table: the latest attempt is queried
  via `idx_intake_runs_source_created (source_revision_id, created_at DESC)`. `intake_runs`
  owns the relationship (one-directional) to avoid bidirectional mutable drift.

- Plain `CREATE TABLE`/`CREATE INDEX` (no `IF NOT EXISTS`): a versioned migration must fail
  loudly on unexpected pre-existing shape rather than mask drift. Idempotency comes from the
  `schema_migrations` ledger (the runner skips already-applied migrations), not from `IF NOT
  EXISTS`.

The runner wraps `up(conn)` in one BEGIN/COMMIT and owns the ledger insert; `up` must NOT commit.

FK note: enforcement of the `intake_runs.source_revision_id` foreign key requires
`PRAGMA foreign_keys=ON` on the connection (orchestrator concern, not this migration). No FK from
`intake_capability_id` yet — the indexed reference is sufficient until that relationship's
deletion policy is migration-safe (WO-4 territory).
"""

from __future__ import annotations

import sqlite3

from app.db.migrations import Migration


def _up(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE intake_source_revisions (
            source_revision_id        TEXT PRIMARY KEY,
            canonical_source_ref      TEXT NOT NULL,
            source_hash_sha256        TEXT NOT NULL,
            byte_size                 INTEGER NOT NULL CHECK (byte_size >= 0),
            policy_snapshot_hash      TEXT NOT NULL,
            adapter_registry_version  TEXT NOT NULL,
            lifecycle_state           TEXT NOT NULL CHECK (
                lifecycle_state IN (
                    'discovered', 'claimed', 'running',
                    'complete', 'failed', 'held', 'quarantined'
                )
            ),
            claim_token               TEXT,
            claimed_by                TEXT,
            claimed_at                TEXT,
            claim_expires_at          TEXT,
            created_at                TEXT NOT NULL,
            last_seen_at              TEXT NOT NULL,
            updated_at                TEXT NOT NULL,
            UNIQUE (
                canonical_source_ref,
                source_hash_sha256,
                policy_snapshot_hash,
                adapter_registry_version
            ),
            UNIQUE (claim_token),
            CHECK (
                (claim_token IS NULL AND claimed_by IS NULL
                    AND claimed_at IS NULL AND claim_expires_at IS NULL)
                OR
                (claim_token IS NOT NULL AND claimed_by IS NOT NULL
                    AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL)
            )
        )
        """
    )
    # State-machine reconciliation: find claimed rows past their lease.
    conn.execute(
        "CREATE INDEX idx_intake_source_revisions_state_claim_expiry "
        "ON intake_source_revisions (lifecycle_state, claim_expires_at)"
    )

    conn.execute(
        """
        CREATE TABLE intake_runs (
            run_id                    TEXT PRIMARY KEY,
            source_revision_id        TEXT,
            source_ref_snapshot       TEXT NOT NULL,
            intake_capability_id      TEXT,
            trigger_kind              TEXT NOT NULL CHECK (
                trigger_kind IN ('scheduler', 'manual', 'replay')
            ),
            lifecycle_state           TEXT NOT NULL CHECK (
                lifecycle_state IN (
                    'created', 'claimed', 'running',
                    'complete', 'failed', 'held', 'quarantined'
                )
            ),
            stage_reached             TEXT NOT NULL DEFAULT 'created',
            failure_code              TEXT,
            failure_detail            TEXT,
            batch_id                  TEXT,
            created_at                TEXT NOT NULL,
            started_at                TEXT,
            finished_at               TEXT,
            updated_at                TEXT NOT NULL,
            FOREIGN KEY (source_revision_id)
                REFERENCES intake_source_revisions (source_revision_id)
        )
        """
    )
    # Latest attempt per revision (replaces the bidirectional last_run_id pointer).
    conn.execute(
        "CREATE INDEX idx_intake_runs_source_created "
        "ON intake_runs (source_revision_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX idx_intake_runs_capability "
        "ON intake_runs (intake_capability_id)"
    )
    conn.execute(
        "CREATE INDEX idx_intake_runs_state_updated "
        "ON intake_runs (lifecycle_state, updated_at)"
    )


MIGRATION = Migration(
    id="0001_intake_orchestration_integrity",
    description=(
        "Add intake_source_revisions (claim-lease state machine) + intake_runs (durable run "
        "audit) ledgers for orchestration idempotency, atomic claim, and structured failure."
    ),
    up=_up,
)

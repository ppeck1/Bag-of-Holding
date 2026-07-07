"""Transaction-aware intake writer — the SQLite unit-of-work for WO-1 (Gate B / B1).

The legacy `db_writer` opens a fresh connection and commits per record, so a stage that must
update several records (capability + trace + run + revision + artifact/quarantine) is NOT atomic.
This module commits a stage's related SQLite state TOGETHER in one transaction on a caller-owned
connection. SQLite is the authoritative orchestration ledger.

Filesystem copies and JSONL appends are NOT performed here — they happen in the pipeline stages
BEFORE the corresponding SQLite transition commits, and remain rebuildable compatibility
artifacts (a failed JSONL append must not roll back a valid SQLite transition; the pipeline logs
it structurally instead).

`canon_eligible` is never written as True — the invariant is asserted before any capability write.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from app.core.planar_service_schemas import (
    AdapterRun,
    IntakeCapability,
    NormalizedArtifact,
    QuarantineRecord,
    RawArtifact,
    TraceEvent,
)
from app.services.intake.clock import utc_now_iso

# Columns an UPDATE may touch on each ledger (allow-list keeps callers from passing arbitrary SQL).
_RUN_UPDATABLE = {
    "source_revision_id", "intake_capability_id", "lifecycle_state", "stage_reached",
    "failure_code", "failure_detail", "batch_id", "started_at", "finished_at",
}
_REVISION_UPDATABLE = {
    "lifecycle_state", "claim_token", "claimed_by", "claimed_at", "claim_expires_at",
    "last_seen_at", "byte_size", "policy_snapshot_hash", "adapter_registry_version",
}


# ── individual record writers (operate on a caller-owned connection) ──────────────

def _write_capability(conn: sqlite3.Connection, cap: IntakeCapability) -> None:
    assert not cap.canon_eligible, "canon_eligible invariant violated before DB write"
    conn.execute(
        """
        INSERT OR REPLACE INTO intake_capabilities (
            intake_capability_id, source_ref, batch_id,
            discovered, preservable, normalizable, interpretable, queryable,
            canon_eligible, required_adapter, safety_lane, failure_reason,
            lifecycle_state, trust_state, authority_default,
            trace_event_refs_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cap.intake_capability_id, cap.source_ref, cap.batch_id,
            int(cap.discovered), int(cap.preservable), int(cap.normalizable),
            int(cap.interpretable), int(cap.queryable),
            cap.required_adapter, cap.safety_lane, cap.failure_reason,
            cap.lifecycle_state, cap.trust_state, cap.authority_default,
            json.dumps(cap.trace_event_refs), utc_now_iso(),
        ),
    )


def _write_trace_event(conn: sqlite3.Connection, te: TraceEvent) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO intake_trace_events (
            trace_event_id, event_type, intake_capability_id, job_id, detail_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (te.trace_event_id, te.event_type, te.intake_capability_id,
         te.job_id, json.dumps(te.detail), utc_now_iso()),
    )


def _write_raw_artifact(conn: sqlite3.Connection, raw: RawArtifact) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO intake_raw_artifacts (
            raw_artifact_id, intake_capability_id, source_ref, batch_id,
            source_hash_sha256, preserved_hash_sha256, byte_size,
            preservation_path, media_type, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (raw.raw_artifact_id, raw.intake_capability_id, raw.source_ref, raw.batch_id,
         raw.source_hash_sha256, raw.preserved_hash_sha256, raw.byte_size,
         raw.preservation_path, raw.media_type, utc_now_iso()),
    )


def _write_normalized_artifact(conn: sqlite3.Connection, norm: NormalizedArtifact) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO intake_normalized_artifacts (
            normalized_artifact_id, raw_artifact_id, adapter_run_id,
            output_path, output_hash_sha256, output_type,
            known_losses_json, warnings_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (norm.normalized_artifact_id, norm.raw_artifact_id, norm.adapter_run_id,
         norm.output_path, norm.output_hash_sha256, norm.output_type,
         json.dumps(norm.known_losses), json.dumps(norm.warnings), utc_now_iso()),
    )


def _write_adapter_run(conn: sqlite3.Connection, run: AdapterRun) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO intake_adapter_runs (
            adapter_run_id, adapter_id, adapter_version,
            raw_artifact_id, intake_capability_id,
            success, failure_reason, warnings_json, output_artifact_ids_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run.adapter_run_id, run.adapter_id, run.adapter_version,
         run.raw_artifact_id, run.intake_capability_id,
         int(run.success), run.failure_reason, json.dumps(run.warnings),
         json.dumps(run.output_artifact_ids), utc_now_iso()),
    )


def _write_quarantine_record(conn: sqlite3.Connection, qr: QuarantineRecord) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO intake_quarantine_records (
            quarantine_record_id, intake_capability_id,
            quarantine_reason, quarantine_category, review_required, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (qr.quarantine_record_id, qr.intake_capability_id,
         qr.quarantine_reason, qr.quarantine_category, int(qr.review_required), utc_now_iso()),
    )


def _apply_run_update(conn: sqlite3.Connection, run_update: dict[str, Any]) -> None:
    run_id = run_update.get("run_id")
    if not run_id:
        raise ValueError("run_update requires 'run_id'")
    cols = [k for k in run_update if k in _RUN_UPDATABLE]
    sets = ", ".join(f"{c}=?" for c in cols) + ", updated_at=?"
    params = [run_update[c] for c in cols] + [utc_now_iso(), run_id]
    conn.execute(f"UPDATE intake_runs SET {sets} WHERE run_id=?", params)


def _apply_revision_update(conn: sqlite3.Connection, rev_update: dict[str, Any]) -> None:
    rid = rev_update.get("source_revision_id")
    if not rid:
        raise ValueError("source_revision_update requires 'source_revision_id'")
    cols = [k for k in rev_update if k in _REVISION_UPDATABLE]
    sets = ", ".join(f"{c}=?" for c in cols) + ", updated_at=?"
    params = [rev_update[c] for c in cols] + [utc_now_iso(), rid]
    conn.execute(f"UPDATE intake_source_revisions SET {sets} WHERE source_revision_id=?", params)


# ── run-row lifecycle ─────────────────────────────────────────────────────────────

def create_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    source_ref_snapshot: str,
    trigger_kind: str,
    source_revision_id: str | None = None,
    intake_capability_id: str | None = None,
    batch_id: str | None = None,
) -> None:
    """Insert a new run row in state 'running' (stage 'created'). source_ref_snapshot is NOT NULL
    so a pre-capability/pre-revision failure is still attributable."""
    now = utc_now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO intake_runs (
                run_id, source_revision_id, source_ref_snapshot, intake_capability_id,
                trigger_kind, lifecycle_state, stage_reached, batch_id,
                created_at, started_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'running', 'created', ?, ?, ?, ?)
            """,
            (run_id, source_revision_id, source_ref_snapshot, intake_capability_id,
             trigger_kind, batch_id, now, now, now),
        )


# ── the unit of work ──────────────────────────────────────────────────────────────

def persist_stage_transition(
    conn: sqlite3.Connection,
    *,
    run_update: dict[str, Any] | None = None,
    source_revision_update: dict[str, Any] | None = None,
    capability: IntakeCapability | None = None,
    trace_events: Iterable[TraceEvent] = (),
    raw_artifact: RawArtifact | None = None,
    normalized_artifact: NormalizedArtifact | None = None,
    adapter_run: AdapterRun | None = None,
    quarantine_record: QuarantineRecord | None = None,
    handoff_row: dict[str, Any] | None = None,
) -> None:
    """Commit one stage's related SQLite state atomically. Either every supplied record is
    written or, on any error, none are (the `with conn:` block rolls back)."""
    with conn:  # one transaction; rolls back on any exception
        if run_update:
            _apply_run_update(conn, run_update)
        if source_revision_update:
            _apply_revision_update(conn, source_revision_update)
        if capability is not None:
            _write_capability(conn, capability)
        for te in trace_events:
            _write_trace_event(conn, te)
        if raw_artifact is not None:
            _write_raw_artifact(conn, raw_artifact)
        if normalized_artifact is not None:
            _write_normalized_artifact(conn, normalized_artifact)
        if adapter_run is not None:
            _write_adapter_run(conn, adapter_run)
        if quarantine_record is not None:
            _write_quarantine_record(conn, quarantine_record)
        if handoff_row is not None:
            _write_handoff_row(conn, handoff_row)


def _write_handoff_row(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Insert the durable promotability record (WO-2 / DEC-0003 provenance bridge)."""
    cols = ", ".join(row.keys())
    marks = ", ".join("?" * len(row))
    conn.execute(f"INSERT INTO intake_handoffs ({cols}) VALUES ({marks})", tuple(row.values()))


_CLEAR_LEASE = ("claim_token=NULL, claimed_by=NULL, claimed_at=NULL, claim_expires_at=NULL")


def finalize_owned(
    conn: sqlite3.Connection,
    *,
    source_revision_id: str,
    claim_token: str | None,
    rev_state: str,
    run_update: dict[str, Any],
    capability: IntakeCapability | None = None,
) -> bool:
    """Terminal transition, atomic and ownership-conditioned. The revision is moved to
    `rev_state` (lease cleared) ONLY while this `claim_token` still owns the claim; the run +
    capability are written in the SAME transaction. Returns False (committing nothing material)
    if ownership was lost — the caller must fail closed and not overwrite a reconciler transition.
    When `claim_token` is None, ownership tracking is disabled and the transition is unconditional
    (preserves the no-token call path)."""
    now = utc_now_iso()
    with conn:  # one transaction
        if claim_token is None:
            conn.execute(
                f"UPDATE intake_source_revisions SET lifecycle_state=?, {_CLEAR_LEASE}, "
                f"updated_at=? WHERE source_revision_id=?",
                (rev_state, now, source_revision_id),
            )
        else:
            cur = conn.execute(
                f"UPDATE intake_source_revisions SET lifecycle_state=?, {_CLEAR_LEASE}, "
                f"updated_at=? WHERE source_revision_id=? AND lifecycle_state='claimed' "
                f"AND claim_token=?",
                (rev_state, now, source_revision_id, claim_token),
            )
            if cur.rowcount != 1:
                return False  # ownership lost — write nothing else
        _apply_run_update(conn, run_update)
        if capability is not None:
            _write_capability(conn, capability)
    return True

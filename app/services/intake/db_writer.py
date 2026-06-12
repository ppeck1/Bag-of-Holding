"""Database persistence for the BOH Governed Ingestion & Translation Layer.

Persists intake pipeline records to SQLite after pipeline completion.
All writes are additive and idempotent (INSERT OR IGNORE / OR REPLACE).
No existing tables are modified.

canon_eligible is never written as True to the database; the schema
enforces DEFAULT 0 and the writer asserts the invariant.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict

from app.core.planar_service_schemas import (
    AdapterRun,
    IntakeCapability,
    NormalizedArtifact,
    RawArtifact,
    QuarantineRecord,
    TraceEvent,
)
from app.db import connection as db


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_capability(cap: IntakeCapability) -> None:
    """Persist an IntakeCapability; canon_eligible is always written as 0."""
    assert not cap.canon_eligible, "canon_eligible invariant violated before DB write"
    db.execute(
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
            cap.intake_capability_id,
            cap.source_ref,
            cap.batch_id,
            int(cap.discovered),
            int(cap.preservable),
            int(cap.normalizable),
            int(cap.interpretable),
            int(cap.queryable),
            cap.required_adapter,
            cap.safety_lane,
            cap.failure_reason,
            cap.lifecycle_state,
            cap.trust_state,
            cap.authority_default,
            json.dumps(cap.trace_event_refs),
            _now(),
        ),
    )


def write_raw_artifact(raw: RawArtifact) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO intake_raw_artifacts (
            raw_artifact_id, intake_capability_id, source_ref, batch_id,
            source_hash_sha256, preserved_hash_sha256, byte_size,
            preservation_path, media_type, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw.raw_artifact_id,
            raw.intake_capability_id,
            raw.source_ref,
            raw.batch_id,
            raw.source_hash_sha256,
            raw.preserved_hash_sha256,
            raw.byte_size,
            raw.preservation_path,
            raw.media_type,
            _now(),
        ),
    )


def write_normalized_artifact(norm: NormalizedArtifact) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO intake_normalized_artifacts (
            normalized_artifact_id, raw_artifact_id, adapter_run_id,
            output_path, output_hash_sha256, output_type,
            known_losses_json, warnings_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            norm.normalized_artifact_id,
            norm.raw_artifact_id,
            norm.adapter_run_id,
            norm.output_path,
            norm.output_hash_sha256,
            norm.output_type,
            json.dumps(norm.known_losses),
            json.dumps(norm.warnings),
            _now(),
        ),
    )


def write_adapter_run(run: AdapterRun) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO intake_adapter_runs (
            adapter_run_id, adapter_id, adapter_version,
            raw_artifact_id, intake_capability_id,
            success, failure_reason, warnings_json,
            output_artifact_ids_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.adapter_run_id,
            run.adapter_id,
            run.adapter_version,
            run.raw_artifact_id,
            run.intake_capability_id,
            int(run.success),
            run.failure_reason,
            json.dumps(run.warnings),
            json.dumps(run.output_artifact_ids),
            _now(),
        ),
    )


def write_quarantine_record(qr: QuarantineRecord) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO intake_quarantine_records (
            quarantine_record_id, intake_capability_id,
            quarantine_reason, quarantine_category,
            review_required, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            qr.quarantine_record_id,
            qr.intake_capability_id,
            qr.quarantine_reason,
            qr.quarantine_category,
            int(qr.review_required),
            _now(),
        ),
    )


def write_trace_event(te: TraceEvent) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO intake_trace_events (
            trace_event_id, event_type, intake_capability_id,
            job_id, detail_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            te.trace_event_id,
            te.event_type,
            te.intake_capability_id,
            te.job_id,
            json.dumps(te.detail),
            _now(),
        ),
    )

"""Replay service for the BOH Governed Ingestion & Translation Layer.

Reprocesses held or failed IntakeCapabilities through the full pipeline.
Reads capability state from the DB, re-runs preservation → normalization
→ queryability → interpretation → handoff, and writes updated records.

Only capabilities in lifecycle_state 'discovered' or 'preserved' with
normalizable=False (i.e., held/failed) are eligible for replay.

No external libraries.  No LLM calls.  No canon mutation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.db import connection as db
from app.services.intake import db_writer
from app.services.intake.capability import initialize_capability
from app.services.intake.normalization import normalize
from app.services.intake.preservation import preserve_file, PreservationConfigError
from app.services.intake.queryability import assess
from app.services.intake.interpretation import produce_evidence_units
from app.services.intake.governance_handoff import assemble_handoff
from app.services.intake.translation_router import route


class ReplayConfigError(Exception):
    """Raised when BOH_DATA_ROOT is not configured."""


def _data_root(data_root: str | None) -> str:
    root = data_root or os.environ.get("BOH_DATA_ROOT", "")
    if not root:
        raise ReplayConfigError(
            "BOH_DATA_ROOT is not set. Replay requires an explicit data root."
        )
    return root


@dataclass
class ReplayResult:
    intake_capability_id: str
    source_ref: str
    success: bool
    stage_reached: str
    route: str | None = None
    normalizable: bool = False
    queryable: bool = False
    evidence_unit_count: int = 0
    handoff_id: str | None = None
    failure_reason: str | None = None


def _capability_context(intake_capability_id: str) -> tuple[dict | None, str | None]:
    """Return (capability_row, stored_source_revision_id) or (None, None) if the capability is
    unknown. The stored revision id is the latest run's source_revision_id for this capability."""
    row = db.fetchone(
        "SELECT * FROM intake_capabilities WHERE intake_capability_id = ?",
        (intake_capability_id,),
    )
    if not row:
        return None, None
    run = db.fetchone(
        "SELECT source_revision_id FROM intake_runs WHERE intake_capability_id = ? "
        "AND source_revision_id IS NOT NULL ORDER BY created_at DESC LIMIT 1",
        (intake_capability_id,),
    )
    return row, (run["source_revision_id"] if run else None)


def reprocess(
    intake_capability_id: str,
    data_root: str | None = None,
) -> ReplayResult:
    """Strict REPLAY of a held/failed capability: re-run its EXACT stored source-revision identity.

    Begins from the stored `source_revision_id`, reproduces the stored execution contract (adapter
    fingerprint + policy snapshot) or fails closed, reclaims the SAME revision, and never mints a
    replacement identity. (This is the `/api/intake/replay` handler; for an intentional contract
    change use `reprocess_under_current_contract`.) Does not raise; failures are in the result."""
    root = _data_root(data_root)
    row, stored_srid = _capability_context(intake_capability_id)
    if row is None:
        return ReplayResult(intake_capability_id=intake_capability_id, source_ref="unknown",
                            success=False, stage_reached="db_lookup",
                            failure_reason=f"Capability {intake_capability_id} not found in DB.")
    source_ref = row["source_ref"]
    batch_id = row["batch_id"]
    if not Path(source_ref).exists():
        return ReplayResult(intake_capability_id=intake_capability_id, source_ref=source_ref,
                            success=False, stage_reached="source_check",
                            failure_reason=f"Source file not found: {source_ref}")
    if stored_srid is None:
        return ReplayResult(intake_capability_id=intake_capability_id, source_ref=source_ref,
                            success=False, stage_reached="no_stored_revision",
                            failure_reason="no stored source_revision_id for this capability")

    from app.services.intake.orchestrator import replay_revision
    result = replay_revision(source_revision_id=stored_srid, source_ref=source_ref,
                             batch_id=batch_id, data_root=root)
    if result.outcome == "already_seen":
        return ReplayResult(intake_capability_id=intake_capability_id, source_ref=source_ref,
                            success=False, stage_reached="not_reclaimable",
                            failure_reason="revision is not in a reclaimable terminal state for replay")
    success = result.outcome == "processed"
    return ReplayResult(
        intake_capability_id=result.intake_capability_id or intake_capability_id,
        source_ref=source_ref, success=success,
        stage_reached="handoff" if success else (result.failure_code or "failed"),
        failure_reason=result.failure_detail if not success else (result.failure_code or None),
    )


def reprocess_under_current_contract(
    intake_capability_id: str,
    data_root: str | None = None,
) -> ReplayResult:
    """Explicit REPROCESS (distinct from replay): re-ingest the capability's source under the CURRENT
    active policy snapshot + adapter-registry fingerprint, MINTING A NEW source-revision identity
    when the contract differs. Records a durable prior->new revision link. Under an unchanged
    contract the identity is unchanged, so the prior (terminal) revision is returned as
    `already_seen` (nothing to reprocess)."""
    root = _data_root(data_root)
    row, prior_srid = _capability_context(intake_capability_id)
    if row is None:
        return ReplayResult(intake_capability_id=intake_capability_id, source_ref="unknown",
                            success=False, stage_reached="db_lookup",
                            failure_reason=f"Capability {intake_capability_id} not found in DB.")
    source_ref = row["source_ref"]
    batch_id = row["batch_id"]
    if not Path(source_ref).exists():
        return ReplayResult(intake_capability_id=intake_capability_id, source_ref=source_ref,
                            success=False, stage_reached="source_check",
                            failure_reason=f"Source file not found: {source_ref}")

    from app.services.intake.orchestrator import execute_intake, link_reprocess_trace
    # Fresh intake under the CURRENT active contract -> a changed contract mints a new identity.
    result = execute_intake(source_ref=source_ref, batch_id=batch_id, trigger_kind="manual",
                            data_root=root)
    if result.outcome == "already_seen":
        return ReplayResult(intake_capability_id=intake_capability_id, source_ref=source_ref,
                            success=False, stage_reached="contract_unchanged",
                            failure_reason="active contract unchanged; identity is identical "
                                           "(use replay to re-run the same revision)")
    success = result.outcome == "processed"
    if success and prior_srid and result.source_revision_id and result.source_revision_id != prior_srid:
        link_reprocess_trace(prior_source_revision_id=prior_srid,
                             new_source_revision_id=result.source_revision_id,
                             new_capability_id=result.intake_capability_id)
    return ReplayResult(
        intake_capability_id=result.intake_capability_id or intake_capability_id,
        source_ref=source_ref, success=success,
        stage_reached="handoff" if success else (result.failure_code or "failed"),
        failure_reason=result.failure_detail if not success else None,
    )


def list_replayable(limit: int = 50) -> list[dict]:
    """Return capabilities eligible for replay: normalizable=False and not quarantined."""
    rows = db.fetchall(
        """
        SELECT intake_capability_id, source_ref, batch_id, lifecycle_state,
               safety_lane, failure_reason, created_at
        FROM intake_capabilities
        WHERE normalizable = 0 AND safety_lane NOT IN ('quarantine', 'ignore')
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return rows

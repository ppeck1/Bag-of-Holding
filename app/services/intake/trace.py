"""Trace event emission helpers for the BOH intake layer.

Every state transition in the intake pipeline must emit a TraceEvent.
This module provides lightweight helpers for constructing trace events
without database access or service wiring.
"""

from __future__ import annotations

from typing import Any

from app.core.planar_service_schemas import TraceEvent, VersionProvenance


def emit(
    event_type: str,
    intake_capability_id: str | None = None,
    job_id: str | None = None,
    detail: dict[str, Any] | None = None,
    policy_snapshot_hash: str | None = None,
) -> TraceEvent:
    """Construct a TraceEvent for a given pipeline transition."""
    prov = VersionProvenance(policy_snapshot_hash=policy_snapshot_hash)
    return TraceEvent(
        event_type=event_type,
        intake_capability_id=intake_capability_id,
        job_id=job_id,
        detail=detail or {},
        version_provenance=prov,
    )


def discovered_event(
    source_ref: str,
    batch_id: str,
    intake_capability_id: str,
    job_id: str | None = None,
) -> TraceEvent:
    return emit(
        event_type="discovered",
        intake_capability_id=intake_capability_id,
        job_id=job_id,
        detail={"source_ref": source_ref, "batch_id": batch_id},
    )


def stabilization_event(
    source_ref: str,
    intake_capability_id: str,
    stable: bool,
    reason: str | None = None,
    job_id: str | None = None,
) -> TraceEvent:
    return emit(
        event_type="stabilized" if stable else "stabilization_failed",
        intake_capability_id=intake_capability_id,
        job_id=job_id,
        detail={"source_ref": source_ref, "stable": stable, "reason": reason},
    )


def excluded_event(
    source_ref: str,
    reason: str,
    job_id: str | None = None,
) -> TraceEvent:
    return emit(
        event_type="excluded",
        job_id=job_id,
        detail={"source_ref": source_ref, "reason": reason},
    )

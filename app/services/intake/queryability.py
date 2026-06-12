"""Queryability assessment for the BOH Governed Ingestion & Translation Layer.

Examines a NormalizedArtifact to determine whether its content is suitable
for retrieval indexing.  Sets IntakeCapability.queryable=True only on
affirmative assessment.

Rules:
- output_type must be text-bearing (markdown, text, json, yaml, csv)
- output file must exist and be readable
- content must meet a minimum word threshold (MIN_QUERYABLE_WORDS)
- hold/quarantine routes are never queryable

No external libraries.  No database access.  No route or UI wiring.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core.planar_service_schemas import (
    IntakeCapability,
    NormalizedArtifact,
    TraceEvent,
    VersionProvenance,
)
from app.services.intake import trace as trace_module


MIN_QUERYABLE_WORDS = 5

_QUERYABLE_OUTPUT_TYPES = {"markdown", "text", "json", "yaml", "csv"}


class QueryabilityConfigError(Exception):
    """Raised when BOH_DATA_ROOT is not configured."""


def _data_root(data_root: str | None) -> str:
    root = data_root or os.environ.get("BOH_DATA_ROOT", "")
    if not root:
        raise QueryabilityConfigError(
            "BOH_DATA_ROOT is not set. Queryability assessment requires an explicit data root."
        )
    return root


@dataclass
class QueryabilityResult:
    queryable: bool
    word_count: int
    capability: IntakeCapability
    normalized_artifact: NormalizedArtifact
    trace_events: list[TraceEvent] = field(default_factory=list)
    failure_reason: str | None = None


def assess(
    normalized_artifact: NormalizedArtifact,
    capability: IntakeCapability,
    data_root: str | None = None,
    policy_snapshot_hash: str | None = None,
) -> QueryabilityResult:
    """Assess whether a NormalizedArtifact is queryable.

    Returns a QueryabilityResult.  On success, capability.queryable=True and
    capability.interpretable=True.  On failure, both remain False.
    """
    root = _data_root(data_root)

    if normalized_artifact.output_type not in _QUERYABLE_OUTPUT_TYPES:
        reason = f"Output type '{normalized_artifact.output_type}' is not text-bearing."
        capability.queryable = False
        te = trace_module.emit(
            "queryability_skipped",
            intake_capability_id=capability.intake_capability_id,
            detail={"reason": reason, "output_type": normalized_artifact.output_type},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return QueryabilityResult(
            queryable=False, word_count=0,
            capability=capability,
            normalized_artifact=normalized_artifact,
            trace_events=[te],
            failure_reason=reason,
        )

    output_path = normalized_artifact.output_path
    if not os.path.isabs(output_path):
        output_path = str(Path(root) / output_path)

    if not Path(output_path).exists():
        reason = f"Normalized output not found: {normalized_artifact.output_path}"
        capability.queryable = False
        te = trace_module.emit(
            "queryability_failed",
            intake_capability_id=capability.intake_capability_id,
            detail={"reason": reason},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return QueryabilityResult(
            queryable=False, word_count=0,
            capability=capability,
            normalized_artifact=normalized_artifact,
            trace_events=[te],
            failure_reason=reason,
        )

    try:
        content = Path(output_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        reason = f"Could not read normalized output: {exc}"
        capability.queryable = False
        te = trace_module.emit(
            "queryability_failed",
            intake_capability_id=capability.intake_capability_id,
            detail={"reason": reason},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return QueryabilityResult(
            queryable=False, word_count=0,
            capability=capability,
            normalized_artifact=normalized_artifact,
            trace_events=[te],
            failure_reason=reason,
        )

    word_count = len(content.split())
    if word_count < MIN_QUERYABLE_WORDS:
        reason = f"Content too short for queryability: {word_count} words (min {MIN_QUERYABLE_WORDS})."
        capability.queryable = False
        te = trace_module.emit(
            "queryability_skipped",
            intake_capability_id=capability.intake_capability_id,
            detail={"reason": reason, "word_count": word_count},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return QueryabilityResult(
            queryable=False, word_count=word_count,
            capability=capability,
            normalized_artifact=normalized_artifact,
            trace_events=[te],
            failure_reason=reason,
        )

    capability.queryable = True
    capability.interpretable = True
    te = trace_module.emit(
        "queryable",
        intake_capability_id=capability.intake_capability_id,
        detail={
            "word_count": word_count,
            "output_type": normalized_artifact.output_type,
            "output_path": normalized_artifact.output_path,
        },
    )
    capability.trace_event_refs.append(te.trace_event_id)
    return QueryabilityResult(
        queryable=True, word_count=word_count,
        capability=capability,
        normalized_artifact=normalized_artifact,
        trace_events=[te],
    )

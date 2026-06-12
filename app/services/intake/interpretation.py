"""Interpretation service for the BOH Governed Ingestion & Translation Layer.

Produces EvidenceUnit records from queryable NormalizedArtifacts.  Each
evidence unit spans the full normalized content (a single body unit) and
carries a content hash.  Span segmentation (heading/body/table splitting)
is deferred to Phase 7+ chunking infrastructure.

No external libraries.  No database access.  No route or UI wiring.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core.planar_service_schemas import (
    EvidenceUnit,
    IntakeCapability,
    NormalizedArtifact,
    TraceEvent,
    VersionProvenance,
)
from app.services.intake import trace as trace_module


class InterpretationConfigError(Exception):
    """Raised when BOH_DATA_ROOT is not configured."""


def _data_root(data_root: str | None) -> str:
    root = data_root or os.environ.get("BOH_DATA_ROOT", "")
    if not root:
        raise InterpretationConfigError(
            "BOH_DATA_ROOT is not set. Interpretation requires an explicit data root."
        )
    return root


@dataclass
class InterpretationResult:
    success: bool
    capability: IntakeCapability
    normalized_artifact: NormalizedArtifact
    evidence_units: list[EvidenceUnit] = field(default_factory=list)
    trace_events: list[TraceEvent] = field(default_factory=list)
    failure_reason: str | None = None


def produce_evidence_units(
    normalized_artifact: NormalizedArtifact,
    capability: IntakeCapability,
    data_root: str | None = None,
    policy_snapshot_hash: str | None = None,
) -> InterpretationResult:
    """Produce EvidenceUnit records from a NormalizedArtifact.

    Currently emits one whole-document body unit.  Finer span segmentation
    is reserved for Phase 7 chunking infrastructure.

    Returns InterpretationResult.  On success, capability.interpretable=True
    and one or more EvidenceUnit records are attached.
    """
    root = _data_root(data_root)
    prov = VersionProvenance(policy_snapshot_hash=policy_snapshot_hash)

    output_path = normalized_artifact.output_path
    if not os.path.isabs(output_path):
        output_path = str(Path(root) / output_path)

    if not Path(output_path).exists():
        reason = f"Normalized output not found: {normalized_artifact.output_path}"
        capability.interpretable = False
        te = trace_module.emit(
            "interpretation_failed",
            intake_capability_id=capability.intake_capability_id,
            detail={"reason": reason},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return InterpretationResult(
            success=False, capability=capability,
            normalized_artifact=normalized_artifact,
            trace_events=[te], failure_reason=reason,
        )

    try:
        content = Path(output_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        reason = f"Could not read normalized output: {exc}"
        capability.interpretable = False
        te = trace_module.emit(
            "interpretation_failed",
            intake_capability_id=capability.intake_capability_id,
            detail={"reason": reason},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return InterpretationResult(
            success=False, capability=capability,
            normalized_artifact=normalized_artifact,
            trace_events=[te], failure_reason=reason,
        )

    content_bytes = content.encode("utf-8", errors="replace")
    text_hash = hashlib.sha256(content_bytes).hexdigest()

    eu = EvidenceUnit(
        normalized_artifact_id=normalized_artifact.normalized_artifact_id,
        span_start=0,
        span_end=len(content),
        unit_type="body",
        text_hash=text_hash,
        authority_default="none",
        version_provenance=prov,
    )

    capability.interpretable = True
    te = trace_module.emit(
        "interpreted",
        intake_capability_id=capability.intake_capability_id,
        detail={
            "evidence_unit_count": 1,
            "evidence_unit_id": eu.evidence_unit_id,
            "output_type": normalized_artifact.output_type,
            "span_end": eu.span_end,
        },
    )
    capability.trace_event_refs.append(te.trace_event_id)

    return InterpretationResult(
        success=True, capability=capability,
        normalized_artifact=normalized_artifact,
        evidence_units=[eu],
        trace_events=[te],
    )

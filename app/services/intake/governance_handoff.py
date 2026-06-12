"""Governance handoff service for the BOH Governed Ingestion & Translation Layer.

Assembles a HandoffPacket from the outputs of all prior intake stages and
emits a trace event.  The HandoffPacket is the formal boundary between the
intake layer and Planar Governance.

HandoffPacket.__post_init__ enforces canon_eligible=False; this module never
attempts to override that invariant.

No external libraries.  No database access.  No route or UI wiring.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.planar_service_schemas import (
    EvidenceUnit,
    HandoffPacket,
    IntakeCapability,
    NormalizedArtifact,
    RawArtifact,
    TraceEvent,
    VersionProvenance,
)
from app.services.intake import trace as trace_module


@dataclass
class HandoffResult:
    success: bool
    capability: IntakeCapability
    handoff_packet: HandoffPacket | None = None
    trace_events: list[TraceEvent] = field(default_factory=list)
    failure_reason: str | None = None


def assemble_handoff(
    capability: IntakeCapability,
    raw_artifact: RawArtifact | None = None,
    normalized_artifact: NormalizedArtifact | None = None,
    evidence_units: list[EvidenceUnit] | None = None,
    policy_snapshot_hash: str | None = None,
) -> HandoffResult:
    """Assemble a HandoffPacket for Planar Governance.

    Emits 'handoff_ready' when normalized_artifact is present and queryable,
    'handoff_skipped' otherwise.  The capability_state dict is produced from
    IntakeCapability.to_dict() which always has canon_eligible=False.

    Returns HandoffResult.  HandoffPacket is always produced (even for
    skipped/hold cases) so Planar Governance has a complete audit record.
    """
    prov = VersionProvenance(policy_snapshot_hash=policy_snapshot_hash)
    eu_list = evidence_units or []
    is_ready = (
        normalized_artifact is not None
        and capability.queryable
        and capability.normalizable
    )

    event_type = "handoff_ready" if is_ready else "handoff_skipped"

    try:
        packet = HandoffPacket(
            intake_capability_id=capability.intake_capability_id,
            capability_state=capability.to_dict(),
            safety_lane=capability.safety_lane,
            raw_artifact_id=raw_artifact.raw_artifact_id if raw_artifact else None,
            normalized_artifact_id=(
                normalized_artifact.normalized_artifact_id
                if normalized_artifact else None
            ),
            evidence_candidate_refs=[eu.evidence_unit_id for eu in eu_list],
            required_adapter=capability.required_adapter,
            failure_reason=capability.failure_reason,
            warnings=[],
            trace_event_refs=list(capability.trace_event_refs),
            version_provenance=prov,
        )
    except ValueError as exc:
        reason = f"HandoffPacket construction failed: {exc}"
        te = trace_module.emit(
            "handoff_error",
            intake_capability_id=capability.intake_capability_id,
            detail={"reason": reason},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return HandoffResult(
            success=False, capability=capability,
            trace_events=[te], failure_reason=reason,
        )

    te = trace_module.emit(
        event_type,
        intake_capability_id=capability.intake_capability_id,
        detail={
            "handoff_id": packet.handoff_id,
            "safety_lane": capability.safety_lane,
            "queryable": capability.queryable,
            "normalizable": capability.normalizable,
            "evidence_unit_count": len(eu_list),
        },
    )
    capability.trace_event_refs.append(te.trace_event_id)
    packet.trace_event_refs.append(te.trace_event_id)

    return HandoffResult(
        success=True, capability=capability,
        handoff_packet=packet,
        trace_events=[te],
    )

"""IntakeCapability initialization for discovered candidates.

Creates IntakeCapability records from discovery results.  Integrates
with the AdapterRegistry to assign required_adapter, safety_lane, and
failure_reason at discovery time.

No database access.  No file preservation.  No normalization.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.planar_service_schemas import IntakeCapability, TraceEvent, VersionProvenance
from app.services.intake.adapter_registry import AdapterRegistry, get_registry
from app.services.intake import trace as trace_module


@dataclass
class InitializedCandidate:
    """Result of initializing an IntakeCapability for a single candidate path."""

    capability: IntakeCapability
    trace_event: TraceEvent
    media_type: str | None = None


def initialize_capability(
    source_ref: str,
    batch_id: str,
    job_id: str | None = None,
    media_type: str | None = None,
    policy_snapshot_hash: str | None = None,
    registry: AdapterRegistry | None = None,
) -> InitializedCandidate:
    """Create an IntakeCapability for a single discovered file.

    The capability starts with:
    - discovered=True
    - all other capability booleans=False
    - safety_lane=hold (default)
    - required_adapter and failure_reason from the adapter registry
    - canon_eligible=False (invariant, enforced by schema)
    """
    reg = registry or get_registry()
    prov = VersionProvenance(policy_snapshot_hash=policy_snapshot_hash)

    adapter_meta, required_adapter, failure_reason = reg.resolve(source_ref, media_type=media_type)

    # Safety lane comes from the adapter's declared default
    safety_lane = adapter_meta.default_safety_lane

    cap = IntakeCapability(
        source_ref=source_ref,
        batch_id=batch_id,
        discovered=True,
        preservable=False,
        normalizable=False,
        interpretable=False,
        queryable=False,
        canon_eligible=False,
        required_adapter=required_adapter,
        safety_lane=safety_lane,
        failure_reason=failure_reason,
        lifecycle_state="discovered",
        trust_state="unknown",
        authority_default="none",
        version_provenance=prov,
    )

    te = trace_module.discovered_event(
        source_ref=source_ref,
        batch_id=batch_id,
        intake_capability_id=cap.intake_capability_id,
        job_id=job_id,
    )
    cap.trace_event_refs.append(te.trace_event_id)

    return InitializedCandidate(
        capability=cap,
        trace_event=te,
        media_type=media_type,
    )


def initialize_batch(
    source_refs: list[str],
    batch_id: str,
    job_id: str | None = None,
    policy_snapshot_hash: str | None = None,
    registry: AdapterRegistry | None = None,
) -> list[InitializedCandidate]:
    """Initialize IntakeCapability records for a list of discovered paths."""
    return [
        initialize_capability(
            source_ref=ref,
            batch_id=batch_id,
            job_id=job_id,
            policy_snapshot_hash=policy_snapshot_hash,
            registry=registry,
        )
        for ref in source_refs
    ]

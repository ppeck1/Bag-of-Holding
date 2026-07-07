"""Translation router for the BOH Governed Ingestion & Translation Layer.

Examines each IntakeCapability and its RawArtifact to determine the
normalization route.  Produces a RouteDecision that the normalization
service executes.

Route decisions:
- direct_stage: adapter can normalize directly (md, txt, code, json, yaml, csv)
- html_neutralize: HTML adapter strips scripts/forms/iframes and records warnings
- hold: adapter exists but normalization requires sandbox or explicit installer
- quarantine: file type is blocked (archive, executable)
- ignore: file was filtered at discovery and should not be processed

No file I/O in this module; routing is pure logic over metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.core.planar_service_schemas import IntakeCapability
from app.services.intake.adapter_registry import AdapterRegistry, get_registry


RouteKind = Literal["direct_stage", "html_neutralize", "hold", "quarantine", "ignore"]

# Adapters that produce HTML output needing neutralization
_HTML_ADAPTERS = {"html_adapter"}

# Adapters that have can_normalize=False (hold for external sandbox/tool)
_HOLD_ADAPTERS = {"pdf_hold", "docx_hold", "image_hold"}

# Adapters that block at the safety lane level
_QUARANTINE_ADAPTERS = {"archive_hold", "executable_block"}


@dataclass
class RouteDecision:
    route: RouteKind
    adapter_id: str
    reason: str
    warnings: list[str] = field(default_factory=list)


def route(
    capability: IntakeCapability,
    registry: AdapterRegistry | None = None,
) -> RouteDecision:
    """Return the normalization route for an IntakeCapability."""
    reg = registry or get_registry()

    source_ref = capability.source_ref
    meta, required_adapter, failure_reason = reg.resolve(source_ref)

    adapter_id = meta.adapter_id

    if adapter_id in _QUARANTINE_ADAPTERS or capability.safety_lane == "quarantine":
        return RouteDecision(
            route="quarantine",
            adapter_id=adapter_id,
            reason=failure_reason or f"Adapter '{adapter_id}' quarantines this file type.",
        )

    if adapter_id in _HOLD_ADAPTERS or not meta.can_normalize:
        return RouteDecision(
            route="hold",
            adapter_id=adapter_id,
            reason=failure_reason or f"Adapter '{adapter_id}' requires sandbox or explicit installer.",
        )

    if adapter_id in _HTML_ADAPTERS:
        return RouteDecision(
            route="html_neutralize",
            adapter_id=adapter_id,
            reason="HTML content requires script/form/iframe neutralization.",
        )

    if meta.can_normalize:
        return RouteDecision(
            route="direct_stage",
            adapter_id=adapter_id,
            reason=f"Adapter '{adapter_id}' supports direct staging.",
        )

    return RouteDecision(
        route="hold",
        adapter_id=adapter_id,
        reason="No normalization path available.",
    )

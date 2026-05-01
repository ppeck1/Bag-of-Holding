"""app/api/routes/temporal_governor_routes.py: Temporal Coherence Governor API.

Phase 24.2 routes. All Fixes A-F exposed as explicit, auditable endpoints.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.temporal_governor import (
    DRIFT_PRIORITY_LEVELS,
    DRIFT_RISK_LEVELS,
    OPEN_ITEM_STATUSES,
    VALID_PLANES,
    create_open_item,
    evaluate_drift,
    evaluate_drift_all,
    expire_stale_open_items,
    get_anchor,
    get_open_item,
    list_anchors,
    list_open_items,
    resolve_open_item,
    resume_on_single_plane,
    temporal_integrity_panel,
    temporal_laundering_check,
    trigger_re_anchor,
)

router = APIRouter(prefix="/api/temporal", tags=["temporal-governor"])


# ---------------------------------------------------------------------------
# Fix A — Drift Detection
# ---------------------------------------------------------------------------

@router.get("/drift/{node_id:path}", summary="Fix A: Evaluate drift risk for one node")
def api_evaluate_drift(node_id: str):
    result = evaluate_drift(node_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("errors", []))
    return result


@router.get("/drift", summary="Fix A: Evaluate drift risk across all nodes")
def api_evaluate_drift_all(
    plane: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    return evaluate_drift_all(plane=plane, limit=limit)


# ---------------------------------------------------------------------------
# Fix B — Nanny Clause / Re-Anchor
# ---------------------------------------------------------------------------

class ReAnchorRequest(BaseModel):
    node_id: str
    actor: str = "human"
    trigger_reason: str = "drift condition detected"
    metadata: dict = {}


@router.post("/re-anchor", summary="Fix B: Trigger Nanny Clause — interrupt, reduce, re-anchor")
def api_trigger_re_anchor(req: ReAnchorRequest):
    """Force d=0, m=contain and return mandatory trinary output.

    This endpoint represents the Nanny Clause. It cannot be bypassed
    by conversational continuity. The trinary form is mandatory.
    """
    result = trigger_re_anchor(
        node_or_card_id=req.node_id,
        actor=req.actor,
        trigger_reason=req.trigger_reason,
        metadata=req.metadata,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result


@router.get("/anchors", summary="Fix B: List anchor events")
def api_list_anchors(
    node_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return {"anchors": list_anchors(node_id=node_id, status=status, limit=limit)}


@router.get("/anchors/{anchor_id}", summary="Fix B: Get one anchor event")
def api_get_anchor(anchor_id: str):
    anchor = get_anchor(anchor_id)
    if not anchor:
        raise HTTPException(status_code=404, detail="anchor event not found")
    return {"anchor": anchor}


# ---------------------------------------------------------------------------
# Fix C — Single Plane Resume
# ---------------------------------------------------------------------------

class ResumePlaneRequest(BaseModel):
    anchor_id: str
    active_plane: str
    actor: str = "human"
    promotion_reason: str


@router.post("/resume", summary="Fix C: Resume on a single active plane after re-anchor")
def api_resume_on_single_plane(req: ResumePlaneRequest):
    """Grant resume in exactly one plane after a re-anchor.

    Multi-plane expansion from this endpoint is prohibited.
    Additional planes require subsequent explicit promotion.
    """
    result = resume_on_single_plane(
        anchor_id=req.anchor_id,
        active_plane=req.active_plane,
        actor=req.actor,
        promotion_reason=req.promotion_reason,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result


# ---------------------------------------------------------------------------
# Fix D — Open Item Registry
# ---------------------------------------------------------------------------

class OpenItemRequest(BaseModel):
    plane_boundary: str
    resolution_authority: str
    drift_priority: str = "moderate"
    description: str
    node_id: Optional[str] = None
    valid_until: Optional[str] = None
    context_ref: dict = {}
    metadata: dict = {}


class ResolveItemRequest(BaseModel):
    resolved_by: str
    resolution_note: str = ""


@router.post("/open-items", summary="Fix D: Register an unresolved ambiguity")
def api_create_open_item(req: OpenItemRequest):
    result = create_open_item(
        plane_boundary=req.plane_boundary,
        resolution_authority=req.resolution_authority,
        drift_priority=req.drift_priority,
        description=req.description,
        node_id=req.node_id,
        valid_until=req.valid_until,
        context_ref=req.context_ref,
        metadata=req.metadata,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result


@router.get("/open-items", summary="Fix D: List open items — unresolved ambiguity persists visibly")
def api_list_open_items(
    status: Optional[str] = Query(None),
    drift_priority: Optional[str] = Query(None),
    node_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return {
        "items": list_open_items(
            status=status,
            drift_priority=drift_priority,
            node_id=node_id,
            limit=limit,
        ),
        "statuses": OPEN_ITEM_STATUSES,
        "drift_priorities": DRIFT_PRIORITY_LEVELS,
    }


@router.post("/open-items/expire-stale", summary="Fix D: Mark items past valid_until as expired")
def api_expire_stale():
    return expire_stale_open_items()


@router.get("/open-items/{item_id}", summary="Fix D: Get one open item")
def api_get_open_item(item_id: str):
    item = get_open_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="open item not found")
    return {"item": item}


@router.post("/open-items/{item_id}/resolve", summary="Deprecated direct resolve gate — canonical resolution requires /api/governance/resolve")
def api_resolve_open_item(item_id: str, req: ResolveItemRequest):
    # Phase 24.3 hardening: this route may no longer bypass identity/team/role/scope validation.
    result = resolve_open_item(
        item_id=item_id,
        resolved_by=req.resolved_by,
        resolution_note=req.resolution_note,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=403, detail={
            "status": "rejected",
            "reason": result.get("reason", "authority_required"),
            "message": "Canonical resolution requires server-side authority validation through /api/governance/resolve.",
            "raw": result,
        })
    return result


# ---------------------------------------------------------------------------
# Fix E — Temporal Laundering Warning
# ---------------------------------------------------------------------------

@router.get("/laundering-check/{node_id:path}", summary="Fix E: Detect temporal laundering")
def api_laundering_check(node_id: str):
    """Return explicit temporal laundering warning if elapsed time has been
    mistaken for verification. Warning must not be suppressed.
    """
    result = temporal_laundering_check(node_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("errors", []))
    return result


# ---------------------------------------------------------------------------
# Fix F — Temporal Integrity Panel
# ---------------------------------------------------------------------------

@router.get("/integrity-panel", summary="Fix F: Temporal Integrity Panel — first-order trust boundary")
def api_integrity_panel(limit: int = Query(50, ge=1, le=200)):
    """Return the full temporal integrity panel.

    Displays: active verified states, open containment states,
    expired without refresh, highest drift risk nodes,
    required resolution authority.

    This is the trust boundary. It must be first-order visible.
    """
    return temporal_integrity_panel(limit=limit)


@router.get("/schema", summary="Temporal Governor schema and constants")
def api_schema():
    return {
        "drift_risk_levels": DRIFT_RISK_LEVELS,
        "open_item_statuses": OPEN_ITEM_STATUSES,
        "drift_priority_levels": DRIFT_PRIORITY_LEVELS,
        "valid_planes": sorted(VALID_PLANES),
        "nanny_clause": {
            "description": "When drift_risk=high, re-anchor is mandatory.",
            "forced_state": {"d": 0, "m": "contain"},
            "output_form": "KNOWN / UNKNOWN / BLOCKED trinary",
            "resume_rule": "single_active_plane only; further expansion requires explicit promotion",
        },
        "temporal_laundering_warning": (
            "Elapsed time does not constitute verification. "
            "This state degraded into containment, not certainty."
        ),
    }

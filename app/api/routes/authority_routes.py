"""app/api/routes/authority_routes.py: Authority enforcement + promotion routes.

Phase 26 additions:
  - /validate now includes legibility payload in rejected responses (26D)
  - /gated-resolve now includes legibility payload in rejected responses (26D)
  - /explain endpoint: translate any block result into user-legible explanation (26D)
  - /sc3/check endpoint: SC3 constitutive boundary check (26C)
  - /sc3/promotion-gate endpoint: SC3 canonical promotion plane gate (26C)
  - /sc3/violations endpoint: audit trail of SC3 constitutive violations (26C)
  - /sc3/mapping endpoint: full SC3 constitutive/descriptive mapping (26C)
"""
from __future__ import annotations
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.core.authority_guard import (
    ActorProfile, validate_resolution_authority, promote_resolution_authority,
    authority_gated_resolve, authority_gated_resume,
    list_authority_log, list_promotions, get_promotion,
)
from app.core.legibility import explain_block, explain_sc3_block, explain_any_block
from app.core.sc3_constitutive import (
    sc3_constitutive_check, sc3_promotion_gate, sc3_map_node_to_plane,
    list_sc3_violations, sc3_mapping_summary,
    _ensure_sc3_violations_table,
)

router = APIRouter(prefix="/api/authority", tags=["authority"])

class ActorProfileModel(BaseModel):
    actor_id: str
    actor_role: str = ""
    actor_team: str = ""
    actor_scope: str = ""
    actor_plane_authority: str = ""

class ValidateRequest(BaseModel):
    actor: ActorProfileModel
    required_authority: str
    target_id: str
    target_type: str = "open_item"
    metadata: dict = {}

class PromoteRequest(BaseModel):
    old_authority: str
    new_authority: str
    promotion_reason: str
    approved_by: str
    target_id: Optional[str] = None
    target_type: Optional[str] = None
    lineage_ref: Optional[str] = None
    metadata: dict = {}

class GatedResolveRequest(BaseModel):
    actor: ActorProfileModel
    resolution_note: str = ""

class GatedResumeRequest(BaseModel):
    actor: ActorProfileModel
    anchor_id: str
    active_plane: str
    promotion_reason: str
    required_authority: str = "governance"

@router.post("/validate", summary="Fix A: Validate resolution authority for an actor (26D: legibility included)")
def api_validate(req: ValidateRequest):
    actor = ActorProfile(**req.actor.model_dump())
    result = validate_resolution_authority(
        actor, req.required_authority, req.target_id, req.target_type, req.metadata
    )
    if not result.get("authorized"):
        result["legibility"] = explain_block(result)
    return result

@router.post("/promote", summary="Fix B: Promote resolution authority with signed lineage")
def api_promote(req: PromoteRequest):
    result = promote_resolution_authority(
        old_authority=req.old_authority, new_authority=req.new_authority,
        promotion_reason=req.promotion_reason, approved_by=req.approved_by,
        target_id=req.target_id, target_type=req.target_type,
        lineage_ref=req.lineage_ref, metadata=req.metadata,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result

@router.get("/promotions", summary="List authority promotions")
def api_list_promotions(target_id: Optional[str] = Query(None), limit: int = Query(100)):
    return {"promotions": list_promotions(target_id=target_id, limit=limit)}

@router.get("/promotions/{promotion_id}", summary="Get one authority promotion")
def api_get_promotion(promotion_id: str):
    p = get_promotion(promotion_id)
    if not p:
        raise HTTPException(status_code=404, detail="promotion not found")
    return {"promotion": p}

@router.get("/log", summary="Fix A: List authority resolution log — all attempts preserved")
def api_log(
    target_id: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    authorized_only: Optional[bool] = Query(None),
    limit: int = Query(100),
):
    return {"log": list_authority_log(target_id=target_id, actor_id=actor_id,
                                      authorized_only=authorized_only, limit=limit)}

@router.post("/gated-resolve/{item_id}", summary="Fix A: Authority-gated open item resolution (26D: legibility included)")
def api_gated_resolve(item_id: str, req: GatedResolveRequest):
    actor = ActorProfile(**req.actor.model_dump())
    result = authority_gated_resolve(actor, item_id, req.resolution_note)
    if not result.get("ok"):
        result["legibility"] = explain_any_block(result, action_type="open_item_resolution")
        raise HTTPException(status_code=403 if "authorized" in result else 400,
                            detail=result)
    return result

@router.post("/gated-resume", summary="Fix A: Authority-gated single-plane resume")
def api_gated_resume(req: GatedResumeRequest):
    actor = ActorProfile(**req.actor.model_dump())
    result = authority_gated_resume(
        actor, req.anchor_id, req.active_plane,
        req.promotion_reason, req.required_authority,
    )
    if not result.get("ok"):
        result["legibility"] = explain_any_block(result, action_type="anchor_resume")
        raise HTTPException(status_code=403 if "authorized" in result else 400,
                            detail=result)
    return result


# ---------------------------------------------------------------------------
# Phase 26D — Legibility endpoints
# ---------------------------------------------------------------------------

class ExplainBlockRequest(BaseModel):
    result: dict[str, Any]
    action_type: str = "unknown_action"

@router.post("/explain", summary="26D: Translate any blocked action result into a user-legible explanation")
def api_explain(req: ExplainBlockRequest):
    """Given any rejected/blocked result dict, return a structured legible explanation.

    The legibility layer answers:
        WHY was this blocked? (specific, not generic)
        WHO must resolve it? (named, not abstract)
        WHAT is the escalation state?
        WHAT happens next?
        WHY can I not override it?
    """
    return explain_any_block(req.result, action_type=req.action_type)


# ---------------------------------------------------------------------------
# Phase 26C — SC3 constitutive boundary routes
# ---------------------------------------------------------------------------

class SC3CheckRequest(BaseModel):
    action: str

class SC3PromotionGateRequest(BaseModel):
    doc_id: str
    doc_metadata: dict[str, Any] = {}
    target_state: str = "canonical"
    requested_by: str
    target_doc_id: Optional[str] = None
    target_doc_metadata: dict[str, Any] = {}

class SC3PlaneInferRequest(BaseModel):
    metadata: dict[str, Any]

@router.post("/sc3/check", summary="26C: Check whether an action is constitutive or descriptive (SC3 closure)")
def api_sc3_check(req: SC3CheckRequest):
    """Return whether an action is constitutive (SC3-enforced) or descriptive (advisory only).

    Constitutive: SC3 registration MUST change system behavior.
    Descriptive: SC3 registration provides orientation only.
    """
    return sc3_constitutive_check(req.action)

@router.post("/sc3/promotion-gate", summary="26C: SC3 constitutive gate for canonical promotion")
def api_sc3_promotion_gate(req: SC3PromotionGateRequest):
    """Apply SC3 plane hierarchy enforcement to a canonical promotion attempt.

    Blocks if source document's epistemic plane lacks authority to overwrite
    the target canonical plane. Returns legibility payload on block.
    """
    _ensure_sc3_violations_table()
    result = sc3_promotion_gate(
        doc_id=req.doc_id,
        doc_metadata=req.doc_metadata,
        target_state=req.target_state,
        requested_by=req.requested_by,
        target_doc_id=req.target_doc_id,
        target_doc_metadata=req.target_doc_metadata or None,
    )
    if result.get("sc3_blocked"):
        result["legibility"] = explain_sc3_block(result)
    return result

@router.post("/sc3/infer-plane", summary="26C: Infer the SC3 epistemic plane for a node from its metadata")
def api_sc3_infer_plane(req: SC3PlaneInferRequest):
    """Infer which SC3 epistemic plane (physical/informational/subjective) a node belongs to."""
    plane = sc3_map_node_to_plane(req.metadata)
    return {
        "plane": plane,
        "metadata_provided": req.metadata,
        "description": {
            "physical": "empirical, sensor data, measurement, observation",
            "informational": "structured knowledge, policy, codified facts",
            "subjective": "interpretation, inference, opinion, LLM synthesis",
        }.get(plane, plane),
    }

@router.get("/sc3/violations", summary="26C: Audit trail of SC3 constitutive violations")
def api_sc3_violations(
    action: Optional[str] = Query(None),
    node_id: Optional[str] = Query(None),
    limit: int = Query(100),
):
    """List all recorded SC3 constitutive violations (permanent audit trail)."""
    _ensure_sc3_violations_table()
    return {"violations": list_sc3_violations(action=action, node_id=node_id, limit=limit)}

@router.get("/sc3/mapping", summary="26C: Full SC3 constitutive/descriptive mapping — the architecture decision")
def api_sc3_mapping():
    """Return the complete SC3 constitutive/descriptive zone mapping.

    This is the Phase 26C architectural decision document:
    - Which actions are constitutive (SC3 enforced)
    - Which are descriptive (SC3 advisory)
    - Mutation rules for each zone
    - BOH → SC3 coordinate mapping
    """
    return sc3_mapping_summary()


# ---------------------------------------------------------------------------
# Phase 26.1 — Translation layer routes
# ---------------------------------------------------------------------------

from app.core.translation import (
    full_translation_map, user_label, translate_status,
    translate_mode, legibility_passes_test,
)


class TranslateRequest(BaseModel):
    label: str

class TranslateStatusRequest(BaseModel):
    status: str


@router.get("/translation/map", summary="26.1: Full user-facing translation table — internal name → UI label")
def api_translation_map():
    """Return the complete Phase 26.1 translation table.

    Maps internal architecture names to user-facing operational labels.
    Internal architecture (Daenary, Rubrix, Atlas, SC3) is NOT renamed.
    Only user-facing surface labels are translated.
    """
    return full_translation_map()


@router.post("/translation/label", summary="26.1: Translate a single internal label to user-facing form")
def api_translate_label(req: TranslateRequest):
    translated = user_label(req.label)
    passes = legibility_passes_test(req.label)
    return {
        "internal": req.label,
        "user_facing": translated,
        "already_legible": passes,
        "changed": translated != req.label,
    }


@router.post("/translation/status", summary="26.1: Translate an internal status value to user-facing label")
def api_translate_status(req: TranslateStatusRequest):
    return {
        "internal_status": req.status,
        "user_facing_label": translate_status(req.status),
    }


@router.post("/translation/mode", summary="26.1: Translate a visualization mode key to user-facing label")
def api_translate_mode(req: TranslateRequest):
    return {
        "internal_mode": req.label,
        "user_facing_label": translate_mode(req.label),
    }

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.feedback_rewrite import (
    FEEDBACK_KINDS,
    REWRITE_ACTIONS,
    apply_feedback_rewrite,
    feedback_topology_status,
    get_rewrite,
    list_rewrites,
    preview_feedback_rewrite,
    revert_feedback_rewrite,
)

router = APIRouter(prefix="/api/feedback", tags=["feedback-rewrite"])


class FeedbackRewriteRequest(BaseModel):
    feedback_kind: str
    action: str
    reason: str
    actor: str = "human"
    edge_id: Optional[str] = None
    source_id: Optional[str] = None
    target_id: Optional[str] = None
    relation: Optional[str] = None
    weight_delta: Optional[float] = None
    new_weight: Optional[float] = None
    new_relation: Optional[str] = None
    constraint_target: Optional[str] = None
    plane: str = "Review"
    authority_plane: str = "governance"
    metadata: dict = {}


class RevertRewriteRequest(BaseModel):
    actor: str = "human"
    reason: str = "manual revert"


@router.get("/schema", summary="Show legal Phase 23 feedback rewrite kinds and actions")
def api_schema():
    return {"feedback_kinds": sorted(FEEDBACK_KINDS), "actions": sorted(REWRITE_ACTIONS)}


@router.post("/rewrite", summary="Apply an auditable, reversible feedback topology rewrite")
def api_apply_feedback_rewrite(req: FeedbackRewriteRequest):
    result = apply_feedback_rewrite(**req.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result


@router.get("/rewrites", summary="List feedback rewrites")
def api_list_rewrites(
    edge_id: Optional[str] = Query(None),
    node_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return {"rewrites": list_rewrites(edge_id=edge_id, node_id=node_id, limit=limit)}


@router.get("/rewrites/{rewrite_id}", summary="Get one feedback rewrite")
def api_get_rewrite(rewrite_id: str):
    rewrite = get_rewrite(rewrite_id)
    if not rewrite:
        raise HTTPException(status_code=404, detail="feedback rewrite not found")
    return {"rewrite": rewrite}


@router.post("/rewrites/{rewrite_id}/revert", summary="Revert a feedback rewrite")
def api_revert_rewrite(rewrite_id: str, req: RevertRewriteRequest):
    result = revert_feedback_rewrite(rewrite_id, actor=req.actor, reason=req.reason)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result


@router.get("/status", summary="Feedback topology safety/status summary")
def api_feedback_status():
    return feedback_topology_status()


@router.post("/preview", summary="P7: Simulate a rewrite and return a constraint diff preview (read-only)")
def api_preview_feedback_rewrite(req: FeedbackRewriteRequest):
    """Return a full topology change preview before the operator approves application.

    This endpoint is read-only. It never writes to the database.
    Operators must review this preview before calling POST /api/feedback/rewrite.
    """
    result = preview_feedback_rewrite(**req.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result

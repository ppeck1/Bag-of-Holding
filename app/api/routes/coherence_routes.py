from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.coherence_decay import (
    DECAY_STATES,
    coherence_summary,
    coherence_warnings,
    evaluate_all_coherence,
    evaluate_node_coherence,
    list_refresh_events,
    record_refresh_event,
    refresh_requirements,
    review_queue_resurfacing,
    stale_state_detection,
)

router = APIRouter(prefix="/api/coherence", tags=["coherence"])


class RefreshRequest(BaseModel):
    node_id: str
    refresh_type: str = "review"
    amount: float = 0.15
    reason: str
    actor: str = "human"
    evidence_refs: list[str] = []
    metadata: dict = {}


@router.get("/summary", summary="Phase 24 coherence decay summary")
def api_coherence_summary():
    return coherence_summary()


@router.get("/nodes/{node_id:path}", summary="Evaluate one node's coherence decay")
def api_node_coherence(node_id: str):
    result = evaluate_node_coherence(node_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("errors", []))
    return result


@router.get("/scores", summary="Evaluate coherence decay for lattice nodes")
def api_scores(plane: Optional[str] = Query(None), limit: int = Query(500, ge=1, le=1000)):
    return evaluate_all_coherence(plane=plane, limit=limit)


@router.get("/stale", summary="Detect stale node states")
def api_stale(limit: int = Query(100, ge=1, le=500)):
    return {"results": stale_state_detection(limit=limit), "states": DECAY_STATES}


@router.get("/warnings", summary="List coherence warnings")
def api_warnings(limit: int = Query(100, ge=1, le=500)):
    return {"results": coherence_warnings(limit=limit)}


@router.get("/refresh-required", summary="List nodes requiring refresh")
def api_refresh_required(limit: int = Query(100, ge=1, le=500)):
    return {"results": refresh_requirements(limit=limit)}


@router.get("/review-queue", summary="Surface decay items for review queue")
def api_review_queue(limit: int = Query(100, ge=1, le=500)):
    return {"results": review_queue_resurfacing(limit=limit)}


@router.get("/refresh-events", summary="List coherence refresh events")
def api_refresh_events(node_id: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500)):
    return {"events": list_refresh_events(node_id=node_id, limit=limit)}


@router.post("/refresh-events", summary="Record a bounded coherence refresh event")
def api_record_refresh(req: RefreshRequest):
    result = record_refresh_event(
        node_id=req.node_id,
        refresh_type=req.refresh_type,
        amount=req.amount,
        reason=req.reason,
        actor=req.actor,
        evidence_refs=req.evidence_refs,
        metadata=req.metadata,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result

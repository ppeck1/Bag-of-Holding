"""app/api/routes/integrity_routes.py: Integrity-First Surface + Visual States."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Query
from app.core.integrity_surface import (
    integrity_first_dashboard, compute_visual_state,
    VISUAL_STATES, DASHBOARD_SECTION_ORDER,
)
from app.core.temporal_governor import evaluate_drift

router = APIRouter(prefix="/api/integrity", tags=["integrity"])

@router.get("/dashboard", summary="Fix E: Integrity-first primary dashboard — truth precedes content")
def api_integrity_dashboard(limit: int = Query(50, ge=1, le=200)):
    return integrity_first_dashboard(limit=limit)

@router.get("/visual-state/{node_id:path}", summary="Fix F: Compute explicit visual state for a node")
def api_visual_state(node_id: str):
    result = evaluate_drift(node_id)
    if not result.get("ok"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=result.get("errors", []))
    drift = result["drift"]
    visual = compute_visual_state(drift)
    return {"node_id": node_id, "visual_state": visual, "drift": drift}

@router.get("/schema", summary="Fix E+F: Visual state vocabulary and dashboard section order")
def api_schema():
    return {
        "visual_states": VISUAL_STATES,
        "dashboard_section_order": DASHBOARD_SECTION_ORDER,
        "principle": "Truth precedes content. Always.",
    }

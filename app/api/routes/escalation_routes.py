"""app/api/routes/escalation_routes.py: Temporal Escalation Ladder routes."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.core.temporal_escalation import (
    ESCALATION_LEVELS, register_escalation_route,
    list_escalation_routes, get_escalation_route,
    run_escalation, escalate_all, get_escalation, list_escalations,
)

router = APIRouter(prefix="/api/escalation", tags=["escalation"])

class EscalationRouteRequest(BaseModel):
    plane: str
    severity: str
    owner: str
    supervisor: str
    max_resolution_window_hours: int = 48
    promotion_rule: str = "supervisor_takes_authority_after_window_expiry"
    containment_required: bool = True
    metadata: dict = {}

@router.post("/registry", summary="Fix D: Register an escalation routing rule")
def api_register_route(req: EscalationRouteRequest):
    result = register_escalation_route(**req.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result

@router.get("/registry", summary="Fix D: List escalation routing registry")
def api_list_routes(plane: Optional[str] = Query(None)):
    return {"routes": list_escalation_routes(plane=plane),
            "levels": ESCALATION_LEVELS}

@router.get("/registry/{plane}/{severity}", summary="Fix D: Get escalation route for plane+severity")
def api_get_route(plane: str, severity: str):
    route = get_escalation_route(plane, severity)
    if not route:
        raise HTTPException(status_code=404, detail="no route registered for this plane+severity")
    return {"route": route}

@router.post("/run/{node_id:path}", summary="Fix C: Run escalation ladder for one node")
def api_run_escalation(node_id: str):
    result = run_escalation(node_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("errors", []))
    return result

@router.post("/run-all", summary="Fix C: Run escalation sweep across all nodes")
def api_escalate_all(plane: Optional[str] = Query(None), limit: int = Query(200)):
    return escalate_all(plane=plane, limit=limit)

@router.get("/events", summary="Fix C: List escalation events")
def api_list_escalations(
    node_id: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    limit: int = Query(100),
):
    return {"escalations": list_escalations(node_id=node_id, level=level, limit=limit)}

@router.get("/events/{escalation_id}", summary="Fix C: Get one escalation event")
def api_get_escalation(escalation_id: str):
    esc = get_escalation(escalation_id)
    if not esc:
        raise HTTPException(status_code=404, detail="escalation event not found")
    return {"escalation": esc}

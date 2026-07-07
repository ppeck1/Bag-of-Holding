"""Phase 28 actor, authority, responsibility, ledger, and attribution routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import OPERATOR_HEADER, require_operator
from app.core import actor_ledger as al


router = APIRouter(prefix="/api", tags=["actors"])


class ActorRequest(BaseModel):
    actor_id: Optional[str] = None
    display_name: str
    actor_type: str = "human"
    source: Optional[str] = None
    external_ref: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True


class ActorPatch(BaseModel):
    display_name: Optional[str] = None
    source: Optional[str] = None
    external_ref: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class AliasRequest(BaseModel):
    alias: str
    source: Optional[str] = None


class GrantRequest(BaseModel):
    actor_id: str
    action: str
    scope_type: str = "global"
    scope_id: Optional[str] = None
    authority_level: str = "operator"
    constraints_json: Any = {}
    granted_by: Optional[str] = "local_operator"
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    active: bool = True


class GrantPatch(BaseModel):
    authority_level: Optional[str] = None
    constraints_json: Any = None
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    active: Optional[bool] = None


class ResponsibilityRequest(BaseModel):
    actor_id: str
    target_type: str
    target_id: str
    responsibility_type: str
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
    status: str = "active"
    assigned_by: Optional[str] = "local_operator"


class AttributionRequest(BaseModel):
    actor_id: Optional[str] = None
    attribution_type: str
    confidence: Optional[float] = 1.0
    source: Optional[str] = None
    evidence_json: Any = None


def _actor_header(x_boh_actor_id: Optional[str] = Header(default=None, alias="X-BOH-Actor-ID")) -> str:
    return al.actor_from_env_or_header(x_boh_actor_id)


@router.get("/actors")
def list_actors(actor_type: Optional[str] = Query(None), active: Optional[int] = Query(None)):
    return {"actors": al.list_actors(actor_type=actor_type, active=active)}


@router.post("/actors")
def create_actor(req: ActorRequest, actor_id: str = Depends(_actor_header),
                 _operator: str = Depends(require_operator)):
    try:
        actor = al.create_actor(req.model_dump())
        al.ledger_event("create_actor", "actor", actor["actor_id"], actor_id=actor_id,
                        authority_result="allowed", authority_basis="operator_token_fallback",
                        after=actor, source_route="/api/actors")
        return actor
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/actors/{actor_id}")
def get_actor(actor_id: str):
    actor = al.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="actor not found")
    actor["aliases"] = al.actor_aliases(actor_id)
    return actor


@router.patch("/actors/{actor_id}")
def update_actor(actor_id: str, req: ActorPatch, current_actor: str = Depends(_actor_header),
                 _operator: str = Depends(require_operator)):
    before = al.get_actor(actor_id)
    if not before:
        raise HTTPException(status_code=404, detail="actor not found")
    try:
        actor = al.update_actor(actor_id, req.model_dump(exclude_unset=True))
    except KeyError:
        raise HTTPException(status_code=404, detail="actor not found")
    al.ledger_event("update_actor", "actor", actor_id, actor_id=current_actor,
                    authority_result="allowed", authority_basis="operator_token_fallback",
                    before=before, after=actor, source_route=f"/api/actors/{actor_id}")
    return actor


@router.post("/actors/{actor_id}/aliases")
def create_alias(actor_id: str, req: AliasRequest, current_actor: str = Depends(_actor_header),
                 _operator: str = Depends(require_operator)):
    try:
        alias = al.add_alias(actor_id, req.alias, req.source)
    except KeyError:
        raise HTTPException(status_code=404, detail="actor not found")
    al.ledger_event("create_actor_alias", "actor", actor_id, actor_id=current_actor,
                    authority_result="allowed", authority_basis="operator_token_fallback",
                    after=alias, source_route=f"/api/actors/{actor_id}/aliases")
    return alias


@router.get("/actors/{actor_id}/ledger")
def actor_ledger(actor_id: str, limit: int = Query(100, ge=1, le=500)):
    return {"events": al.recent_ledger(actor_id=actor_id, limit=limit)}


@router.get("/authority/grants")
def list_grants(actor_id: Optional[str] = Query(None), action: Optional[str] = Query(None),
                scope_type: Optional[str] = Query(None), scope_id: Optional[str] = Query(None)):
    return {"grants": al.list_grants(actor_id=actor_id, action=action, scope_type=scope_type, scope_id=scope_id)}


@router.post("/authority/grants")
def create_grant(req: GrantRequest, current_actor: str = Depends(_actor_header),
                 _operator: str = Depends(require_operator)):
    try:
        grant = al.create_grant(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    al.ledger_event("create_authority_grant", "authority_grant", grant["grant_id"],
                    actor_id=current_actor, authority_result="allowed",
                    authority_basis="operator_token_fallback", after=grant,
                    source_route="/api/authority/grants")
    return grant


@router.patch("/authority/grants/{grant_id}")
def update_grant(grant_id: str, req: GrantPatch, current_actor: str = Depends(_actor_header),
                 _operator: str = Depends(require_operator)):
    before = al.get_grant(grant_id)
    if not before:
        raise HTTPException(status_code=404, detail="grant not found")
    grant = al.update_grant(grant_id, req.model_dump(exclude_unset=True))
    al.ledger_event("update_authority_grant", "authority_grant", grant_id,
                    actor_id=current_actor, authority_result="allowed",
                    authority_basis="operator_token_fallback", before=before, after=grant,
                    source_route=f"/api/authority/grants/{grant_id}")
    return grant


@router.get("/responsibility/assignments")
def list_responsibility(actor_id: Optional[str] = Query(None), target_type: Optional[str] = Query(None),
                        target_id: Optional[str] = Query(None)):
    return {"assignments": al.list_responsibility(actor_id=actor_id, target_type=target_type, target_id=target_id)}


@router.post("/responsibility/assignments")
def assign_responsibility(req: ResponsibilityRequest, current_actor: str = Depends(_actor_header),
                          _operator: str = Depends(require_operator)):
    assignment = al.assign_responsibility(req.model_dump())
    al.ledger_event("assign_responsibility", req.target_type, req.target_id,
                    actor_id=current_actor, authority_result="allowed",
                    authority_basis="operator_token_fallback", after=assignment,
                    source_route="/api/responsibility/assignments")
    return assignment


@router.get("/ledger/recent")
def recent_ledger(limit: int = Query(100, ge=1, le=500), actor_id: Optional[str] = Query(None),
                  target_type: Optional[str] = Query(None), target_id: Optional[str] = Query(None)):
    return {"events": al.recent_ledger(limit=limit, actor_id=actor_id, target_type=target_type, target_id=target_id)}


@router.get("/docs/{doc_id}/attribution")
def doc_attribution(doc_id: str):
    return {"doc_id": doc_id, "attribution": al.get_document_attribution(doc_id)}


@router.post("/docs/{doc_id}/attribution")
def add_doc_attribution(doc_id: str, req: AttributionRequest, current_actor: str = Depends(_actor_header),
                        _operator: str = Depends(require_operator)):
    attr = al.add_document_attribution(
        doc_id,
        req.attribution_type,
        req.actor_id or current_actor,
        confidence=req.confidence,
        source=req.source,
        evidence=req.evidence_json,
    )
    al.ledger_event("add_document_attribution", "document", doc_id, actor_id=current_actor,
                    authority_result="allowed", authority_basis="operator_token_fallback",
                    after=attr, source_route=f"/api/docs/{doc_id}/attribution")
    return attr


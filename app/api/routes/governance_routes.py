"""app/api/routes/governance_routes.py: Workspace policy and audit endpoints.

Phase 10 addition.

  GET  /api/governance/policies               — list all policies
  GET  /api/governance/policy/{workspace}     — get effective policy for entity
  POST /api/governance/policy                 — create/update a policy
  GET  /api/governance/check                  — check a specific permission
  GET  /api/governance/edges                  — query system edges
  POST /api/governance/edges                  — add a system edge
  GET  /api/audit                             — query audit log
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core import governance, audit

router = APIRouter(prefix="/api")


class PolicyRequest(BaseModel):
    workspace:   str
    entity_type: str            # 'human' | 'model' | 'system'
    entity_id:   str = "*"
    can_read:    int = 1
    can_write:   int = 0
    can_execute: int = 0
    can_propose: int = 1
    can_promote: int = 0        # always 0 for models — enforced server-side
    note:        str = ""


class SystemEdgeRequest(BaseModel):
    source_type: str
    source_id:   str
    target_type: str
    target_id:   str
    edge_type:   str
    state:       Optional[int] = None
    detail:      Optional[str] = None


@router.get("/governance/policies", summary="List all workspace policies")
def list_policies(workspace: Optional[str] = Query(None)):
    """Return all workspace policies, optionally filtered by workspace."""
    return {
        "policies": governance.list_policies(workspace=workspace),
        "count": len(governance.list_policies(workspace=workspace)),
    }


@router.get("/governance/policy/{workspace}", summary="Get effective policy for entity on workspace")
def get_effective_policy(
    workspace:   str,
    entity_type: str = Query("human"),
    entity_id:   str = Query("*"),
):
    """Return the effective permissions for an entity on a workspace.

    Resolves: specific rule → wildcard rule → system default.
    """
    return governance.get_effective_policy(workspace, entity_type, entity_id)


@router.post("/governance/policy", summary="Create or update a workspace policy")
def upsert_policy(req: PolicyRequest):
    """Create or replace a workspace access policy.

    Canon protection invariant: can_promote is always forced to 0 for models.
    """
    try:
        return governance.upsert_policy(
            workspace=req.workspace,
            entity_type=req.entity_type,
            entity_id=req.entity_id,
            can_read=req.can_read,
            can_write=req.can_write,
            can_execute=req.can_execute,
            can_propose=req.can_propose,
            can_promote=req.can_promote,
            note=req.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/governance/check", summary="Check a specific permission")
def check_permission(
    workspace:   str          = Query(...),
    entity_type: str          = Query(...),
    permission:  str          = Query(...),
    entity_id:   str          = Query("*"),
):
    """Check whether an entity has a specific permission on a workspace.

    Returns {allowed, reason, policy}.
    """
    return governance.check_permission(
        workspace=workspace,
        entity_type=entity_type,
        permission=permission,
        entity_id=entity_id,
    )


@router.get("/governance/edges", summary="Query system DCNS edges")
def get_system_edges(
    source_type: Optional[str] = Query(None),
    source_id:   Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    target_id:   Optional[str] = Query(None),
    edge_type:   Optional[str] = Query(None),
):
    """Query system-level DCNS edges (authority/flow/scope relationships)."""
    edges = governance.get_system_edges(
        source_type=source_type, source_id=source_id,
        target_type=target_type, target_id=target_id,
        edge_type=edge_type,
    )
    return {"edges": edges, "count": len(edges)}


@router.post("/governance/edges", summary="Add a system DCNS edge")
def add_system_edge(req: SystemEdgeRequest):
    """Add an authority/flow edge between any system node types.

    Source/target types: doc, workspace, model, tool, role
    Edge types: may-read, may-write, may-execute, may-propose, may-promote,
                derives-from, depends-on, promoted-to, conflicts-with
    """
    try:
        return governance.add_system_edge(
            source_type=req.source_type,
            source_id=req.source_id,
            target_type=req.target_type,
            target_id=req.target_id,
            edge_type=req.edge_type,
            state=req.state,
            detail=req.detail,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/audit", summary="Query the governance audit log")
def query_audit(
    doc_id:     Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    actor_type: Optional[str] = Query(None),
    since_ts:   Optional[int] = Query(None),
    limit:      int           = Query(50, ge=1, le=200),
):
    """Return audit events matching the given filters.

    Audit log is append-only. No events are deleted.
    """
    events = audit.get_events(
        doc_id=doc_id, event_type=event_type,
        actor_type=actor_type, since_ts=since_ts, limit=limit,
    )
    return {"events": events, "count": len(events)}

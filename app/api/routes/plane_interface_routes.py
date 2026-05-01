"""Phase 21 Plane Interface API routes."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.plane_interface import create_interface, get_interface, list_interfaces

router = APIRouter(prefix="/api/plane-interfaces", tags=["plane-interfaces"])


class PlaneInterfaceRequest(BaseModel):
    source_plane: str
    target_plane: str
    translation_reason: str
    loss_notes: list[str] = Field(default_factory=list)
    certificate_refs: list[str] = Field(default_factory=list)
    q_delta: float = 0.0
    c_delta: float = 0.0
    authority_plane: str = "verification"
    node_id: Optional[str] = None
    created_by: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


@router.post("", summary="Create an explicit cross-plane interface artifact")
def post_plane_interface(req: PlaneInterfaceRequest):
    result = create_interface(**req.dict())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result


@router.get("", summary="List plane interface artifacts")
def get_plane_interfaces(node_id: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500)):
    interfaces = list_interfaces(node_id=node_id, limit=limit)
    return {"interfaces": interfaces, "count": len(interfaces)}


@router.get("/{interface_id}", summary="Read one plane interface artifact")
def get_plane_interface(interface_id: str):
    interface = get_interface(interface_id)
    if not interface:
        raise HTTPException(status_code=404, detail="plane interface not found")
    return {"interface": interface}

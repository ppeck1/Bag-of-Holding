"""app/api/routes/substrate_routes.py: Phase 25 Substrate Lattice routes."""
from __future__ import annotations
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.core.substrate_lattice import (
    COORDINATE_KEYS, LatticeObject, register_lattice_object,
    get_lattice_object, list_lattice_objects, project_state,
    run_validation_test, _lattice_id,
)

router = APIRouter(prefix="/api/substrate", tags=["substrate-lattice"])

class LatticeObjectRequest(BaseModel):
    domain: str
    label: str
    k_physical: str
    k_informational: str
    k_subjective: str
    x_physical: str
    x_informational: str
    x_subjective: str
    f_physical: str
    f_informational: str
    f_subjective: str
    cpl: dict[str, Any] = {}
    proj: dict[str, Any] = {}
    obs: dict[str, Any] = {}
    requires_new_ontology: bool = False
    validation_notes: str = ""
    metadata: dict[str, Any] = {}

@router.post("/register", summary="Fix G: Register a domain object in the substrate lattice")
def api_register(req: LatticeObjectRequest):
    lid = _lattice_id(req.domain, req.label)
    obj = LatticeObject(lattice_id=lid, **req.model_dump())
    result = register_lattice_object(obj)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors", []))
    return result

@router.get("/objects", summary="Fix G: List registered lattice objects")
def api_list(domain: Optional[str] = Query(None)):
    return {"objects": list_lattice_objects(domain=domain),
            "coordinates": list(COORDINATE_KEYS)}

@router.get("/objects/{lattice_id}", summary="Fix G: Get one lattice object")
def api_get(lattice_id: str):
    obj = get_lattice_object(lattice_id)
    if not obj:
        raise HTTPException(status_code=404, detail="lattice object not found")
    return {"object": obj}

@router.get("/project/{lattice_id}", summary="Fix G: Apply PROJ operator — return observable state")
def api_project(lattice_id: str, observer_context: str = Query("external")):
    result = project_state(lattice_id, observer_context)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("errors", []))
    return result

@router.post("/validate", summary="Fix H: Run anti-bullshit validation test (3 domains, no new tokens)")
def api_validate():
    return run_validation_test()

@router.get("/schema", summary="Phase 25: Scalar-3³ lattice schema and equation")
def api_schema():
    return {
        "equation": "X_{t+1} = Pi_K(F(X_t))",
        "planes": ["physical", "informational", "subjective"],
        "layers": ["constraint (K)", "state (X)", "dynamic (F)"],
        "coordinates": list(COORDINATE_KEYS),
        "additional": {"CPL": "coupling map", "PROJ": "projection operator", "OBS": "observation model"},
    }

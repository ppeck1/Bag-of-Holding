from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.lattice_graph import (
    REQUIRED_EDGE_RELATIONS,
    active_subgraph,
    create_edge,
    get_edge,
    get_node,
    list_edges,
    list_nodes,
    query_collapsing_planes,
    query_harm_flow,
    query_intervention_expands_feasibility,
    query_load_bearing_constraints,
    query_stale_truths,
    runtime_queries,
    traverse_flow,
)

router = APIRouter(prefix="/api/lattice", tags=["lattice"])


class CreateEdgeRequest(BaseModel):
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0
    created_by: str = "human"
    metadata: dict = {}


@router.get("/nodes", summary="List constraint-native lattice nodes")
def api_list_nodes(
    plane: Optional[str] = Query(None),
    node_type: Optional[str] = Query(None),
    active_only: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    nodes = list_nodes(plane=plane, node_type=node_type, active_only=active_only, limit=limit, offset=offset)
    return {"nodes": [n.to_dict() for n in nodes], "count": len(nodes)}


@router.get("/nodes/{node_id:path}", summary="Get one lattice node")
def api_get_node(node_id: str):
    node = get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="lattice node not found")
    return {"node": node.to_dict()}


@router.post("/edges", summary="Create or replace an explicit lattice edge")
def api_create_edge(req: CreateEdgeRequest):
    result = create_edge(req.source_id, req.target_id, req.relation, req.weight, req.created_by, req.metadata)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result["errors"])
    return result


@router.get("/edges", summary="List lattice edges")
def api_list_edges(
    node_id: Optional[str] = Query(None),
    relation: Optional[str] = Query(None),
    active_only: bool = Query(True),
):
    return {"edges": list_edges(node_id=node_id, relation=relation, active_only=active_only), "relations": sorted(REQUIRED_EDGE_RELATIONS)}


@router.get("/edges/{edge_id}", summary="Get lattice edge")
def api_get_edge(edge_id: str):
    edge = get_edge(edge_id)
    if not edge:
        raise HTTPException(status_code=404, detail="lattice edge not found")
    return {"edge": edge}


@router.get("/subgraph", summary="Return active subgraph")
def api_subgraph(plane: Optional[str] = Query(None)):
    return active_subgraph(plane=plane)


@router.get("/flow/{start_node_id:path}", summary="Traverse flow from a node")
def api_flow(start_node_id: str, max_depth: int = Query(4, ge=1, le=8)):
    result = traverse_flow(start_node_id, max_depth=max_depth)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("errors", []))
    return result


@router.get("/queries/load-bearing", summary="What constraint is load-bearing right now?")
def api_load_bearing(limit: int = Query(10, ge=1, le=100)):
    return {"results": query_load_bearing_constraints(limit=limit)}


@router.get("/queries/feasibility", summary="What intervention expands feasibility most?")
def api_feasibility(limit: int = Query(10, ge=1, le=100)):
    return {"results": query_intervention_expands_feasibility(limit=limit)}


@router.get("/queries/harm-flow", summary="Where does harm flow if this fails?")
def api_harm_flow(start_node_id: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200)):
    return {"results": query_harm_flow(start_node_id=start_node_id, limit=limit)}


@router.get("/queries/stale-truths", summary="What truths are stale?")
def api_stale_truths(limit: int = Query(50, ge=1, le=200)):
    return {"results": query_stale_truths(limit=limit)}


@router.get("/queries/collapsing-planes", summary="Which plane is collapsing?")
def api_collapsing_planes():
    return {"results": query_collapsing_planes()}


@router.get("/queries", summary="Run all Phase 22 runtime lattice queries")
def api_runtime_queries():
    return runtime_queries()

"""WO-R2: /api/context-object — Level-5 context objects + Level-3 state retrieval.

Auth posture (roadmap §3.2): X-BOH-Retrieval-Token required, fail-closed — the response
aggregates evidence text, so it takes the most restrictive posture of its inputs. GET serves
simple scopes (`scope=doc:{id}|project:{p}|plane:{p}`); POST takes a JSON body for query scopes
(no overloaded scope=query:{q} string).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core import context_object, retrieval

router = APIRouter(prefix="/api", tags=["context-object"])

_SIMPLE = ("doc", "project", "plane", "node")


def _parse_edge_types(edge_types: Optional[str]) -> Optional[list]:
    if not edge_types:
        return None
    requested = [t.strip() for t in edge_types.split(",") if t.strip()]
    bad = [t for t in requested if t not in context_object.VERIFIED_EDGE_TYPES]
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"edge_types outside the verified stored vocabulary {bad}; "
                   f"allowed: {context_object.VERIFIED_EDGE_TYPES}")
    return requested


class ContextObjectRequest(BaseModel):
    scope: dict = Field(..., description='{"type": "query", "query": "..."} or '
                                         '{"type": "doc|project|plane", "value": "..."}')
    only: Optional[str] = None
    evidence_limit: int = Field(8, ge=1, le=25)
    include_promoted: bool = False
    question_type: Optional[str] = None  # WO-R3: historical|operational|authority|exploratory


@router.get("/context-object", summary="Assemble a governed context object for a simple scope")
def get_context_object(
    scope: str = Query(..., min_length=3, max_length=512,
                       description="doc:{id} | project:{p} | plane:{p}"),
    only: Optional[str] = Query(None, description="'blocking' for the reduced blocker view"),
    evidence_limit: int = Query(8, ge=1, le=25),
    include_promoted: bool = Query(False),
    question_type: Optional[str] = Query(
        None, description="historical | operational | authority | exploratory (WO-R3)"),
    radius: int = Query(1, ge=1, le=2, description="node-scope neighborhood radius (WO-R4)"),
    edge_types: Optional[str] = Query(
        None, description="node-scope CSV filter within the verified stored vocabulary (WO-R4)"),
    _connector: str = Depends(retrieval.require_retrieval_token),
):
    if question_type is not None and question_type not in context_object.QUESTION_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"question_type must be one of {context_object.QUESTION_TYPES}")
    if ":" not in scope:
        raise HTTPException(status_code=422, detail="scope must be '<type>:<value>'")
    scope_type, value = scope.split(":", 1)
    if scope_type not in _SIMPLE or not value:
        raise HTTPException(status_code=422,
                            detail=f"GET scope type must be one of {_SIMPLE} with a value; "
                                   "use POST for query scopes")
    if only not in (None, "blocking"):
        raise HTTPException(status_code=422, detail="only must be omitted or 'blocking'")
    return context_object.assemble(scope_type, value, only=only,
                                   evidence_limit=evidence_limit,
                                   include_promoted=include_promoted,
                                   question_type=question_type,
                                   radius=radius,
                                   edge_types=_parse_edge_types(edge_types))


@router.post("/context-object", summary="Assemble a governed context object (query scopes)")
def post_context_object(
    # Promoted-content contract: query-scope POST follows the STANDARD WO-2 dual gate
    # (BOH_RETRIEVAL_INCLUDE_PROMOTED env AND include_promoted request flag) — not stricter;
    # visible promoted docs surface via evidence packs + the resolved member count.
    req: ContextObjectRequest,
    _connector: str = Depends(retrieval.require_retrieval_token),
):
    stype = (req.scope or {}).get("type")
    value = (req.scope or {}).get("query") if stype == "query" else (req.scope or {}).get("value")
    if stype not in context_object.SCOPE_TYPES or not value:
        raise HTTPException(status_code=422,
                            detail="scope.type must be doc|project|plane|query with a "
                                   "value/query")
    if not isinstance(value, str) or len(value) > 2000:
        raise HTTPException(status_code=422, detail="scope value/query must be <= 2000 chars")
    if req.only not in (None, "blocking"):
        raise HTTPException(status_code=422, detail="only must be omitted or 'blocking'")
    if req.question_type is not None and req.question_type not in context_object.QUESTION_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"question_type must be one of {context_object.QUESTION_TYPES}")
    return context_object.assemble(stype, value, only=req.only,
                                   evidence_limit=req.evidence_limit,
                                   include_promoted=req.include_promoted,
                                   question_type=req.question_type)

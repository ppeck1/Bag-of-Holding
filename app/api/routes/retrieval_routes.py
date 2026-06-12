"""Read-only retrieval API for LLM/connectors."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core import retrieval

router = APIRouter(prefix="/api", tags=["retrieval"])


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(8, ge=1, le=25)
    max_context_chars: int = Field(6000, ge=500, le=30000)
    mode: str = Field("strict_answer")
    include_lineage: bool = True
    doc_id: Optional[str] = None
    status: Optional[str] = None
    authority_state: Optional[str] = None
    canonical_layer: Optional[str] = None
    project: Optional[str] = None
    chunk_type: Optional[str] = None
    # WO-2 dual gate: effective only when BOH_RETRIEVAL_INCLUDE_PROMOTED is also enabled.
    include_promoted: bool = False


@router.get("/retrieve/status", summary="Read-only retrieval connector status")
def retrieve_status():
    return retrieval.retrieval_status()


@router.post("/retrieve", summary="Build ranked, cited context packs for LLM retrieval")
def retrieve_context(
    req: RetrieveRequest,
    _connector: str = Depends(retrieval.require_retrieval_token),
):
    filters = {
        "doc_id": req.doc_id,
        "status": req.status,
        "authority_state": req.authority_state,
        "canonical_layer": req.canonical_layer,
        "project": req.project,
        "chunk_type": req.chunk_type,
    }
    try:
        return retrieval.retrieve_governed(
            req.query,
            mode=req.mode,
            limit=req.limit,
            include_lineage=req.include_lineage,
            filters={k: v for k, v in filters.items() if v},
            max_context_chars=req.max_context_chars,
            include_promoted=req.include_promoted,
        )
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/retrieve", summary="Build ranked, cited context packs for LLM retrieval")
def retrieve_context_get(
    q: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=25),
    max_context_chars: int = Query(6000, ge=500, le=30000),
    mode: str = Query("strict_answer"),
    include_lineage: bool = True,
    doc_id: Optional[str] = None,
    status: Optional[str] = None,
    authority_state: Optional[str] = None,
    canonical_layer: Optional[str] = None,
    project: Optional[str] = None,
    chunk_type: Optional[str] = None,
    include_promoted: bool = Query(False),
    _connector: str = Depends(retrieval.require_retrieval_token),
):
    filters = {
        "doc_id": doc_id,
        "status": status,
        "authority_state": authority_state,
        "canonical_layer": canonical_layer,
        "project": project,
        "chunk_type": chunk_type,
    }
    try:
        return retrieval.retrieve_governed(
            q,
            mode=mode,
            limit=limit,
            include_lineage=include_lineage,
            filters={k: v for k, v in filters.items() if v},
            max_context_chars=max_context_chars,
            include_promoted=include_promoted,
        )
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(exc))

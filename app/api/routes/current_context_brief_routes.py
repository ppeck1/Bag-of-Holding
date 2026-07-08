"""CurrentContextBrief v0.1 API.

Retrieval-token-gated, read-only context search surface for humans and LLM
clients. It composes existing retrieval and context-object evidence without
changing ranking, schema, intake, Canon, or write paths.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core import current_context_brief, retrieval

router = APIRouter(prefix="/api", tags=["current-context"])


class CurrentContextBriefRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(8, ge=1, le=25)
    max_context_chars: int = Field(6000, ge=500, le=30000)
    mode: str = Field("exploration")
    include_promoted: bool = False


@router.post("/current-context-brief", summary="Build a CurrentContextBrief v0.1")
def post_current_context_brief(
    req: CurrentContextBriefRequest,
    _connector: str = Depends(retrieval.require_retrieval_token),
):
    try:
        return current_context_brief.build_current_context_brief(
            req.topic,
            limit=req.limit,
            mode=req.mode,
            include_promoted=req.include_promoted,
            max_context_chars=req.max_context_chars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/current-context-brief", summary="Build a CurrentContextBrief v0.1")
def get_current_context_brief(
    topic: str = Query(..., min_length=1, max_length=2000),
    limit: int = Query(8, ge=1, le=25),
    max_context_chars: int = Query(6000, ge=500, le=30000),
    mode: str = Query("exploration"),
    include_promoted: bool = Query(False),
    _connector: Optional[str] = Depends(retrieval.require_retrieval_token),
):
    try:
        return current_context_brief.build_current_context_brief(
            topic,
            limit=limit,
            mode=mode,
            include_promoted=include_promoted,
            max_context_chars=max_context_chars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

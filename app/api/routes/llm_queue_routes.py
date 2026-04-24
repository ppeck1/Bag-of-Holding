"""app/api/routes/llm_queue_routes.py: LLM Review Queue API for Phase 12.

GET  /api/llm/queue              — list pending (or filtered) items
GET  /api/llm/queue/count        — pending count
POST /api/llm/queue              — enqueue a new LLM proposal
POST /api/llm/queue/{id}/approve — approve (applies safe metadata fields)
POST /api/llm/queue/{id}/reject  — reject (no changes applied)
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import llm_queue

router = APIRouter(prefix="/api")


class EnqueueRequest(BaseModel):
    proposed: dict
    doc_id: Optional[str] = None
    file_path: Optional[str] = None
    model: Optional[str] = None
    invocation_id: Optional[str] = None


class ReviewAction(BaseModel):
    actor: str = "user"
    reason: Optional[str] = None


@router.get("/llm/queue", summary="Get LLM review queue", tags=["llm"])
def get_llm_queue(status: str = "pending", limit: int = 50):
    items = llm_queue.get_queue(status=status, limit=limit)
    return {"status": status, "items": items, "count": len(items)}


@router.get("/llm/queue/count", summary="Get pending LLM review count", tags=["llm"])
def get_queue_count():
    return {"pending": llm_queue.get_pending_count()}


@router.post("/llm/queue", summary="Enqueue an LLM proposal for user review", tags=["llm"])
def enqueue_proposal(req: EnqueueRequest):
    """Add an LLM-generated metadata proposal to the review queue.

    The proposal will not be applied until the user explicitly approves it.
    """
    queue_id = llm_queue.enqueue(
        proposed=req.proposed,
        doc_id=req.doc_id,
        file_path=req.file_path,
        model=req.model,
        invocation_id=req.invocation_id,
    )
    return {"queue_id": queue_id, "status": "pending"}


@router.post(
    "/llm/queue/{queue_id}/approve",
    summary="Approve an LLM proposal (applies safe metadata fields only)",
    tags=["llm"],
)
def approve_proposal(queue_id: str, req: ReviewAction):
    """Approve an LLM proposal.

    SAFETY: canonical status, type=canon, and operator_state=release
    are NEVER applied automatically from an LLM proposal, even on approval.
    """
    result = llm_queue.approve(queue_id, actor=req.actor)
    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post(
    "/llm/queue/{queue_id}/reject",
    summary="Reject an LLM proposal (no document changes)",
    tags=["llm"],
)
def reject_proposal(queue_id: str, req: ReviewAction):
    result = llm_queue.reject(queue_id, actor=req.actor, reason=req.reason)
    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result

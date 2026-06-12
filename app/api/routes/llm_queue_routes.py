"""app/api/routes/llm_queue_routes.py: LLM Review Queue API for Phase 12.

GET  /api/llm/queue              — list pending (or filtered) items
GET  /api/llm/queue/count        — pending count
POST /api/llm/queue              — enqueue a new LLM proposal
POST /api/llm/queue/{id}/approve — approve (applies safe metadata fields)
POST /api/llm/queue/{id}/reject  — reject (no changes applied)
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import require_operator
from app.core import actor_ledger as al
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
def get_llm_queue(status: str = "pending", limit: int = Query(50, ge=1)):
    items = llm_queue.get_queue(status=status, limit=limit)
    return {"status": status, "items": items, "count": len(items)}


@router.get("/llm/queue/count", summary="Get pending LLM review count", tags=["llm"])
def get_queue_count():
    return {"pending": llm_queue.get_pending_count()}


@router.post("/llm/queue", summary="Enqueue an LLM proposal for user review", tags=["llm"])
def enqueue_proposal(req: EnqueueRequest, _operator: str = Depends(require_operator)):
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
    try:
        model_actor = "ollama_local" if req.model else "codex"
        al.ledger_event("llm_proposal", "document", req.doc_id or req.file_path,
                        actor_id=model_actor, authority_result="proposed",
                        authority_basis="llm_advisory_only",
                        after={"queue_id": queue_id, "model": req.model},
                        source_route="/api/llm/queue")
        if req.doc_id:
            al.add_document_attribution(req.doc_id, "proposed_by", model_actor,
                                        source="llm_queue", evidence={"queue_id": queue_id, "model": req.model})
    except Exception:
        pass
    return {"queue_id": queue_id, "status": "pending"}


@router.post(
    "/llm/queue/{queue_id}/approve",
    summary="Approve an LLM proposal (applies safe metadata fields only)",
    tags=["llm"],
)
def approve_proposal(queue_id: str, req: ReviewAction, _operator: str = Depends(require_operator),
                     x_boh_actor_id: Optional[str] = Header(default=None, alias="X-BOH-Actor-ID")):
    """Approve an LLM proposal.

    SAFETY: canonical status, type=canon, and operator_state=release
    are NEVER applied automatically from an LLM proposal, even on approval.
    """
    result = llm_queue.approve(queue_id, actor=req.actor)
    if not result["success"]:
        # 404 when the queue item does not exist; 422 for other state errors.
        code = 404 if "not found" in str(result.get("error", "")).lower() else 422
        raise HTTPException(status_code=code, detail=result["error"])
    actor_id = al.actor_from_env_or_header(x_boh_actor_id, default=req.actor or "local_operator")
    al.ledger_event("approve_proposal", "llm_queue", queue_id, actor_id=actor_id,
                    authority_result="approved", authority_basis="operator_token_fallback",
                    after=result, source_route=f"/api/llm/queue/{queue_id}/approve")
    if result.get("doc_id"):
        al.add_document_attribution(result["doc_id"], "approved_by", actor_id,
                                    source="llm_queue", evidence={"queue_id": queue_id})
    return result


@router.post(
    "/llm/queue/{queue_id}/reject",
    summary="Reject an LLM proposal (no document changes)",
    tags=["llm"],
)
def reject_proposal(queue_id: str, req: ReviewAction, _operator: str = Depends(require_operator),
                    x_boh_actor_id: Optional[str] = Header(default=None, alias="X-BOH-Actor-ID")):
    result = llm_queue.reject(queue_id, actor=req.actor, reason=req.reason)
    if not result["success"]:
        code = 404 if "not found" in str(result.get("error", "")).lower() else 422
        raise HTTPException(status_code=code, detail=result["error"])
    actor_id = al.actor_from_env_or_header(x_boh_actor_id, default=req.actor or "local_operator")
    al.ledger_event("reject_proposal", "llm_queue", queue_id, actor_id=actor_id,
                    authority_result="rejected", authority_basis="operator_token_fallback",
                    after=result, source_route=f"/api/llm/queue/{queue_id}/reject")
    return result

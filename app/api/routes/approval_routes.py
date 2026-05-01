"""app/api/routes/approval_routes.py: Phase 15 explicit governance approval endpoints.

Every authority transfer requires a visible, signed, auditable approval.

Routes:
  POST /api/governance/approve/request-promotion     — request canonical promotion
  POST /api/governance/approve/request-supersede     — request supersede operation
  POST /api/governance/approve/request-patch         — request review artifact patch
  POST /api/governance/approve/request-edge          — request edge promotion
  POST /api/governance/approve/{approval_id}/approve — execute approval
  POST /api/governance/approve/{approval_id}/reject  — reject request
  POST /api/governance/approve/edges/{id}/approve    — approve edge promotion
  GET  /api/governance/approve/pending               — list pending requests
  GET  /api/governance/approve/edges/pending         — list pending edge requests
  GET  /api/governance/approve/{doc_id}/provenance   — provenance chain for doc
  GET  /api/governance/approve/{doc_id}/impact       — impact preview for supersede
  GET  /api/governance/log                           — governance event log
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import approval

router = APIRouter(prefix="/api/governance/approve", tags=["governance-approval"])


# ── Request models ─────────────────────────────────────────────────────────────

class PromotionRequest(BaseModel):
    doc_id:       str
    from_state:   str
    to_state:     str
    requested_by: str
    reason:       str
    diff_hash:    Optional[str] = None
    impact_docs:  Optional[list[str]] = None


class SupersedeRequest(BaseModel):
    current_doc_id:     str
    replacement_doc_id: str
    requested_by:       str
    reason:             str
    affected_count:     int = 0


class PatchRequest(BaseModel):
    doc_id:        str
    patch_summary: str
    diff_hash:     str
    requested_by:  str
    reason:        str
    original_text: Optional[str] = None
    proposed_text: Optional[str] = None
    llm_source:    Optional[str] = None
    review_artifact: Optional[str] = None


class EdgeRequest(BaseModel):
    source_doc_id: str
    target_doc_id: str
    edge_type:     str
    strength:      float = 0.5
    requested_by:  str
    reason:        str
    cross_project: bool = False


class ReviewDecision(BaseModel):
    reviewed_by:  str
    review_note:  str


# ── Request creation ───────────────────────────────────────────────────────────

@router.post("/request-promotion", summary="Request canonical promotion approval")
def request_promotion(req: PromotionRequest):
    """Legacy direct approval-promotion path removed in Phase 20.1.

    Use POST /api/certificate/request, then /api/certificate/review, then
    /api/certificate/apply-canonical-promotion.
    """
    raise HTTPException(
        status_code=410,
        detail="direct_promotion_removed_use_certificate_flow",
    )


@router.post("/request-supersede", summary="Request supersede operation approval")
def request_supersede(req: SupersedeRequest):
    """Request approval to supersede a canonical document.

    Requires explicit acknowledgment of downstream impact.
    Old canonical remains queryable — never destructive replacement.
    """
    result = approval.request_supersede(
        current_doc_id=req.current_doc_id,
        replacement_doc_id=req.replacement_doc_id,
        requested_by=req.requested_by,
        reason=req.reason,
        affected_count=req.affected_count,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/request-patch", summary="Request review artifact patch approval")
def request_patch(req: PatchRequest):
    """Request approval to apply a review artifact patch to a source document.

    Requires diff_hash — the SHA-256 of the proposed content change.
    No auto-merge. No silent overwrite.
    """
    import json
    patch_payload = json.dumps({
        "patch_summary": req.patch_summary,
        "original_text": req.original_text or "",
        "proposed_text": req.proposed_text or "",
        "llm_source": req.llm_source or "undisclosed",
        "review_artifact": req.review_artifact or "",
        "source_document": req.doc_id,
    })
    result = approval.request_review_patch(
        doc_id=req.doc_id,
        patch_summary=patch_payload,
        diff_hash=req.diff_hash,
        requested_by=req.requested_by,
        reason=req.reason,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/request-edge", summary="Request edge promotion from suggested to governed")
def request_edge(req: EdgeRequest):
    """Request promotion of a suggested edge to governed authority.

    Cross-project edges remain suggested until explicitly approved.
    Semantic similarity does not establish authority.
    """
    result = approval.request_edge_promotion(
        source_doc_id=req.source_doc_id,
        target_doc_id=req.target_doc_id,
        edge_type=req.edge_type,
        strength=req.strength,
        requested_by=req.requested_by,
        reason=req.reason,
        cross_project=req.cross_project,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ── Review decisions ───────────────────────────────────────────────────────────

@router.post("/{approval_id}/approve", summary="Approve a pending request")
def approve(approval_id: str, decision: ReviewDecision):
    """Execute an approval — creates immutable provenance artifact and performs state change.

    review_note is required. The provenance artifact is signed and append-only.
    """
    if not decision.review_note or not decision.review_note.strip():
        raise HTTPException(status_code=422, detail="review_note is required for approval.")
    result = approval.approve_request(
        approval_id=approval_id,
        reviewed_by=decision.reviewed_by,
        review_note=decision.review_note,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/{approval_id}/reject", summary="Reject a pending request")
def reject(approval_id: str, decision: ReviewDecision):
    """Reject an approval request. No state change occurs."""
    result = approval.reject_request(
        approval_id=approval_id,
        reviewed_by=decision.reviewed_by,
        review_note=decision.review_note,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/edges/{edge_apr_id}/approve", summary="Approve edge promotion")
def approve_edge(edge_apr_id: str, decision: ReviewDecision):
    """Approve promotion of a suggested edge to governed authority."""
    result = approval.approve_edge(
        edge_apr_id=edge_apr_id,
        reviewed_by=decision.reviewed_by,
        review_note=decision.review_note,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ── Queries ────────────────────────────────────────────────────────────────────

@router.get("/pending", summary="List pending approval requests")
def list_pending(doc_id: Optional[str] = None, limit: int = 50):
    return {"pending": approval.get_pending_approvals(doc_id=doc_id, limit=limit)}


@router.get("/ledger", summary="Constitutional approval ledger")
def approval_ledger(status: Optional[str] = None, action_type: Optional[str] = None, doc_id: Optional[str] = None, limit: int = 200):
    """Query pending/completed/rejected approvals as a constitutional ledger, not just a task queue."""
    return {"ledger": approval.get_approval_ledger(status=status, action_type=action_type, doc_id=doc_id, limit=limit)}


@router.get("/{approval_id}/review-diff", summary="First-class review artifact diff")
def review_diff(approval_id: str):
    """Line-oriented review surface for LLM review artifacts."""
    result = approval.get_review_diff(approval_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.get("/edges/pending", summary="List pending edge approval requests")
def list_pending_edges(limit: int = 50):
    return {"pending": approval.get_pending_edge_approvals(limit=limit)}


@router.get("/{doc_id}/provenance", summary="Get provenance chain for a document")
def get_provenance(doc_id: str):
    """Returns the full signed provenance chain for all authority events on this document."""
    artifacts = approval.get_provenance(doc_id)
    return {
        "doc_id": doc_id,
        "provenance_count": len(artifacts),
        "provenance": artifacts,
    }


@router.get("/{doc_id}/impact", summary="Preview impact of superseding a document")
def impact_preview(doc_id: str):
    """Returns count and list of documents that reference this doc.
    Use before requesting a supersede operation.
    """
    return approval.get_impact_preview(doc_id)

"""app/api/routes/review_queue_routes.py: Phase 7 Review Queue surface.

Exposes the correction-loop patch-proposal queue for inspection and adjudication.
Read routes are open; approve/reject are operator-gated and COMPOSE the existing
frozen `app.core.correction_ledger` functions (this module never re-implements the
adjudication contract: approve still requires regression fixtures unless schema,
always re-forces forbidden_auto_apply, and creates a canon-change record). Every
adjudication writes trace via the ledger's storage-event log.

GET  /api/review-queue/proposals                  — list patch proposals
GET  /api/review-queue/proposals/{patch_id}       — one proposal, or 404
POST /api/review-queue/proposals/{patch_id}/reject  — reject (operator-gated)
POST /api/review-queue/proposals/{patch_id}/approve — approve (operator-gated)
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core import correction_ledger
from app.core.auth import require_operator

router = APIRouter(prefix="/api/review-queue", tags=["review-queue"])

MAX_LIMIT = 200


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (False if k == "canon_eligible" else _sanitize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return _sanitize({k: v for k, v in row.items() if not k.endswith("_json")})


class RejectBody(BaseModel):
    reviewed_by: str
    review_note: str = ""


class ApproveBody(BaseModel):
    approved_by: str
    changed_objects: list[str]
    migration_note: str
    regression_fixture_refs: Optional[list[str]] = None
    old_location_refs: Optional[list[str]] = None
    new_location_refs: Optional[list[str]] = None
    supersedes_refs: Optional[list[str]] = None
    trace_event_ref: Optional[str] = None
    residence_updates: Optional[list[dict[str, Any]]] = None
    review_note: str = ""


def _raise_for_error(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("success") is False:
        err = result.get("error")
        if err == "patch_proposal_not_found":
            raise HTTPException(status_code=404, detail=err)
        if err == "regression_fixture_refs_required":
            raise HTTPException(status_code=422, detail=err)
        raise HTTPException(status_code=400, detail=err or "adjudication_failed")
    return result


@router.get("/proposals", summary="List patch proposals (read-only review queue)")
def list_proposals(
    limit: int = Query(50, ge=1),
    status: Optional[str] = Query(None),
):
    rows = correction_ledger.list_patch_proposals(limit=min(limit, MAX_LIMIT), status=status)
    return {"proposals": [_clean(r) for r in rows]}


@router.get("/proposals/{patch_id}", summary="Get one patch proposal, or 404")
def get_proposal(patch_id: str):
    row = correction_ledger.get_patch_proposal(patch_id)
    if row is None:
        raise HTTPException(status_code=404, detail="patch_proposal_not_found")
    return _clean(row)


@router.post("/proposals/{patch_id}/reject", summary="Reject a patch proposal (operator-gated)")
def reject_proposal(patch_id: str, body: RejectBody, _operator: str = Depends(require_operator)):
    if not body.review_note or not body.review_note.strip():
        raise HTTPException(status_code=422, detail="review_note is required for rejection")
    result = correction_ledger.reject_patch_proposal(
        patch_id, reviewed_by=body.reviewed_by, review_note=body.review_note
    )
    return _clean(_raise_for_error(result))


@router.post("/proposals/{patch_id}/approve", summary="Approve a patch proposal (operator-gated)")
def approve_proposal(patch_id: str, body: ApproveBody, _operator: str = Depends(require_operator)):
    result = correction_ledger.approve_patch_proposal(
        patch_id,
        approved_by=body.approved_by,
        changed_objects=body.changed_objects,
        old_location_refs=body.old_location_refs,
        new_location_refs=body.new_location_refs,
        supersedes_refs=body.supersedes_refs,
        migration_note=body.migration_note,
        regression_fixture_refs=body.regression_fixture_refs,
        trace_event_ref=body.trace_event_ref,
        residence_updates=body.residence_updates,
        review_note=body.review_note,
    )
    return _clean(_raise_for_error(result))

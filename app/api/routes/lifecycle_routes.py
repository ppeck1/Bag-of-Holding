"""app/api/routes/lifecycle_routes.py: Lifecycle undo/backward/history endpoints.

Phase 12 addition. Adds:
  GET  /api/lifecycle/{doc_id}/history       — full lifecycle event log
  GET  /api/lifecycle/{doc_id}/can-backward  — check if backward is possible
  POST /api/lifecycle/{doc_id}/backward      — move one step backward
  POST /api/lifecycle/{doc_id}/undo          — undo most recent change
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import lifecycle, audit

router = APIRouter(prefix="/api")


class BackwardRequest(BaseModel):
    reason: Optional[str] = None
    actor: str = "user"


class UndoRequest(BaseModel):
    actor: str = "user"


@router.get(
    "/lifecycle/{doc_id}/history",
    summary="Get lifecycle event history for a document",
    tags=["lifecycle"],
)
def get_lifecycle_history(doc_id: str, limit: int = 50):
    events = lifecycle.get_history(doc_id, limit=limit)
    return {"doc_id": doc_id, "events": events, "count": len(events)}


@router.get(
    "/lifecycle/{doc_id}/can-backward",
    summary="Check if backward lifecycle movement is possible",
    tags=["lifecycle"],
)
def can_move_backward(doc_id: str):
    return lifecycle.can_move_backward(doc_id)


@router.post(
    "/lifecycle/{doc_id}/backward",
    summary="Move document one step backward in lifecycle",
    tags=["lifecycle"],
)
def move_backward(doc_id: str, req: BackwardRequest):
    """Move a document one step backward (e.g. release → integrate).

    Records a history event. Prior history is never erased.
    Requires a reason note (encouraged but not enforced).
    """
    result = lifecycle.move_backward(doc_id, reason=req.reason, actor=req.actor)
    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["error"])

    audit.log_event(
        "edit",
        actor_type="user",
        actor_id=req.actor,
        doc_id=doc_id,
        detail=json.dumps({
            "action": "lifecycle_backward",
            "from_state": result["previous_state"],
            "to_state": result["new_state"],
            "reason": req.reason,
        }),
    )
    return result


@router.post(
    "/lifecycle/{doc_id}/undo",
    summary="Undo the last lifecycle change for a document",
    tags=["lifecycle"],
)
def undo_lifecycle(doc_id: str, req: UndoRequest):
    """Revert to the from_state of the most recent lifecycle event.

    Appends a new 'undo' history record. Prior history is never deleted.
    """
    result = lifecycle.undo_last(doc_id, actor=req.actor)
    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["error"])

    audit.log_event(
        "edit",
        actor_type="user",
        actor_id=req.actor,
        doc_id=doc_id,
        detail=json.dumps({
            "action": "lifecycle_undo",
            "to_state": result["new_state"],
            "undone_event_id": result.get("undone_event_id"),
        }),
    )
    return result

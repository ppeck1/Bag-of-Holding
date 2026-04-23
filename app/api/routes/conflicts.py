"""app/api/routes/conflicts.py"""
from fastapi import APIRouter, HTTPException
from app.core import conflicts as conflict_engine
from app.db import connection as db

router = APIRouter(prefix="/api")


@router.get("/conflicts", summary="List all detected conflicts")
def list_conflicts():
    all_conflicts = conflict_engine.list_conflicts()
    return {
        "count": len(all_conflicts),
        "conflicts": all_conflicts,
        "note": "No auto-resolution. All conflicts require explicit user action.",
    }


@router.patch("/conflicts/{conflict_rowid}/acknowledge",
              summary="Acknowledge a conflict (marks seen — does not resolve)")
def acknowledge_conflict(conflict_rowid: int):
    """Mark a conflict as acknowledged. The conflict record is preserved — not deleted.
    Acknowledgment is not resolution. See corpus_migration_doctrine §6.
    """
    conflict = db.fetchone(
        "SELECT rowid, * FROM conflicts WHERE rowid = ?", (conflict_rowid,)
    )
    if not conflict:
        raise HTTPException(status_code=404, detail=f"Conflict rowid {conflict_rowid} not found")

    db.execute(
        "UPDATE conflicts SET acknowledged = 1 WHERE rowid = ?", (conflict_rowid,)
    )
    return {
        "acknowledged": True,
        "rowid": conflict_rowid,
        "conflict_type": conflict["conflict_type"],
        "doc_ids": conflict["doc_ids"],
        "term": conflict["term"],
        "note": "Conflict record preserved. No auto-resolution.",
    }

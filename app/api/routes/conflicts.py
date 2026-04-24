"""app/api/routes/conflicts.py: Conflict detection endpoints for Bag of Holding v2.

Phase 9: conflict list enriched with doc titles and paths for human readability.
"""
from fastapi import APIRouter, HTTPException
from app.core import conflicts as conflict_engine
from app.db import connection as db

router = APIRouter(prefix="/api")


def _enrich_conflict(c: dict) -> dict:
    """Attach title+path for each doc_id in a conflict record."""
    doc_ids = [d.strip() for d in (c.get("doc_ids") or "").split(",") if d.strip()]
    enriched_docs = []
    for did in doc_ids:
        row = db.fetchone("SELECT doc_id, title, path, status FROM docs WHERE doc_id = ?", (did,))
        if row:
            enriched_docs.append({
                "doc_id": did,
                "title":  row["title"] or did[:20],
                "path":   row["path"] or "",
                "status": row["status"] or "",
            })
        else:
            enriched_docs.append({"doc_id": did, "title": did[:20], "path": "", "status": ""})
    return {**c, "docs": enriched_docs}


@router.get("/conflicts", summary="List all detected conflicts")
def list_conflicts():
    all_conflicts = conflict_engine.list_conflicts()
    enriched = [_enrich_conflict(c) for c in all_conflicts]
    return {
        "count": len(enriched),
        "conflicts": enriched,
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

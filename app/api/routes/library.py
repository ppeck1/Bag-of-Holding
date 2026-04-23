"""app/api/routes/library.py"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.db import connection as db
from app.services import events as event_engine

router = APIRouter(prefix="/api")


@router.get("/docs", summary="List all documents (paginated)")
def list_docs(
    status: Optional[str] = Query(None, description="Filter by status"),
    doc_type: Optional[str] = Query(None, description="Filter by type", alias="type"),
    operator_state: Optional[str] = Query(None, description="Filter by operator_state"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Results per page"),
):
    """Paginated document list. Closes v0P gap — no list endpoint existed previously."""
    query = "SELECT * FROM docs WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if doc_type:
        query += " AND type = ?"
        params.append(doc_type)
    if operator_state:
        query += " AND operator_state = ?"
        params.append(operator_state)

    query += " ORDER BY updated_ts DESC"

    all_docs = db.fetchall(query, tuple(params))
    total = len(all_docs)
    offset = (page - 1) * per_page
    page_docs = all_docs[offset: offset + per_page]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "count": len(page_docs),
        "docs": page_docs,
    }


@router.get("/docs/{doc_id}", summary="Get a single document by ID")
def get_doc(doc_id: str):
    doc = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    defs = db.fetchall("SELECT * FROM defs WHERE doc_id = ?", (doc_id,))
    evs = event_engine.list_events(doc_id=doc_id)
    return {"doc": doc, "definitions": defs, "events": evs}

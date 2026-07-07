"""app/api/routes/library.py"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from app.db import connection as db
from app.core.auth import require_operator
from app.core.logical_libraries import InvalidLibraryId, docs_where_clause
from app.services import events as event_engine

router = APIRouter(prefix="/api")


@router.get("/docs", summary="List all documents (paginated)")
def list_docs(
    status: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None, alias="type"),
    operator_state: Optional[str] = Query(None),
    authority_state: Optional[str] = Query(None, description="Filter by authority_state"),
    project: Optional[str] = Query(None, description="Filter by project"),
    library_id: Optional[str] = Query(None, description="Logical library browsing scope"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """Paginated document list with authority and project filters (Phase 16.2)."""
    from app.core import promoted_exposure
    query = ("SELECT * FROM docs WHERE 1=1"
             + promoted_exposure.exclusion_sql("", show_promoted=promoted_exposure.env_gate_open()))
    params: list = []
    try:
        library_clause, library_params, library = docs_where_clause(library_id)
    except InvalidLibraryId as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    query += library_clause
    params.extend(library_params)
    if status:
        query += " AND status = ?"
        params.append(status)
    if doc_type:
        query += " AND type = ?"
        params.append(doc_type)
    if operator_state:
        query += " AND operator_state = ?"
        params.append(operator_state)
    if authority_state:
        query += " AND authority_state = ?"
        params.append(authority_state)
    if project:
        query += " AND project = ?"
        params.append(project)

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
        "library": library.to_dict(),
        "docs": page_docs,
    }


@router.get("/docs/{doc_id}", summary="Get a single document by ID")
def get_doc(doc_id: str):
    doc = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # WO-2 audit item E: direct-by-id access to a promoted doc is also env-gated (fail-closed).
    from app.core import promoted_exposure
    if promoted_exposure.is_promoted_row(doc) and not promoted_exposure.env_gate_open():
        raise HTTPException(status_code=404, detail="Document not found")
    defs = db.fetchall("SELECT * FROM defs WHERE doc_id = ?", (doc_id,))
    evs = event_engine.list_events(doc_id=doc_id)
    return {"doc": doc, "definitions": defs, "events": evs}


class DocMetadataPatch(BaseModel):
    project: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    authority_state: Optional[str] = None


@router.patch("/docs/{doc_id}/metadata", summary="Phase 26.2: Patch editable metadata fields on a document")
def patch_doc_metadata(
    doc_id: str,
    patch: DocMetadataPatch,
    _operator: str = Depends(require_operator),
):
    """Patch user-editable metadata fields (project, title, summary, authority_state).

    Only updates fields that are explicitly provided (None = skip).
    Internal fields (status, doc_id, path, etc.) cannot be changed via this route.
    """
    doc = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # WO-2 mutation isolation (gate-independent): ordinary metadata edits are blocked.
    from app.core import promoted_exposure
    if promoted_exposure.is_promoted_row(doc):
        raise HTTPException(status_code=409, detail=promoted_exposure.MUTATION_BLOCK_REASON)

    updates = {}
    if patch.project is not None:
        updates["project"] = patch.project.strip()
    if patch.title is not None:
        updates["title"] = patch.title.strip()
    if patch.summary is not None:
        updates["summary"] = patch.summary.strip()
    if patch.authority_state is not None:
        updates["authority_state"] = patch.authority_state.strip()

    if not updates:
        return {"ok": True, "doc_id": doc_id, "message": "No changes provided", **dict(doc)}

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db.execute(
        f"UPDATE docs SET {set_clause} WHERE doc_id = ?",
        (*updates.values(), doc_id),
    )

    updated = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
    return {"ok": True, "doc_id": doc_id, "updated_fields": list(updates.keys()), "doc": updated}

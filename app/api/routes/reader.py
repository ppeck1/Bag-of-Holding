"""app/api/routes/reader.py: Document reader and graph endpoints for Bag of Holding v2.

Phase 7 — Blueprint implementation:
  GET /api/docs/{id}/content  — raw markdown body (frontmatter stripped)
  GET /api/docs/{id}/related  — semantically related documents
  GET /api/graph              — full graph data (nodes + edges) for Atlas visualization

Phase 8 — Daenary + DCNS additions:
  GET /api/docs/{id}/coordinates  — Daenary coordinate dimensions for a document
  POST /api/dcns/sync             — rebuild doc_edges from lineage + conflicts
"""

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.db import connection as db
from app.services.parser import parse_frontmatter_full
from app.core.related import get_related, get_graph_data
from app.core.daenary import get_coordinates, format_coordinate_summary

router = APIRouter(prefix="/api")

LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")


def _resolve_doc_path(doc: dict) -> Path | None:
    """Resolve doc path relative to library root. Tries multiple root candidates."""
    root = Path(os.environ.get("BOH_LIBRARY", LIBRARY_ROOT)).resolve()
    p = root / (doc["path"] or "")
    if p.exists():
        return p
    # Try relative to cwd
    p2 = Path(doc["path"] or "")
    if p2.exists():
        return p2
    return None


@router.get("/docs/{doc_id}/content",
            response_class=PlainTextResponse,
            summary="Get raw markdown body of a document (frontmatter stripped)")
def get_doc_content(doc_id: str):
    """Returns the markdown body text of a document, with YAML frontmatter removed.

    Used by the client-side markdown renderer.
    Returns 404 if document not found or file not on disk.
    """
    doc = db.fetchone("SELECT path FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    full_path = _resolve_doc_path(doc)
    if not full_path:
        raise HTTPException(
            status_code=404,
            detail=f"File not found on disk: {doc['path']} (library root: {os.environ.get('BOH_LIBRARY', LIBRARY_ROOT)})"
        )

    text = full_path.read_text(encoding="utf-8", errors="replace")
    _, _raw, body, _ = parse_frontmatter_full(text)
    return body


@router.get("/docs/{doc_id}/related",
            summary="Get semantically related documents")
def get_doc_related(
    doc_id: str,
    limit: int = Query(8, ge=1, le=30),
):
    """Returns documents related to the given doc_id, ranked by semantic similarity.

    Scoring: 0.45×topic_overlap + 0.25×scope_overlap + 0.20×lineage + 0.10×shared_defs
    """
    doc = db.fetchone("SELECT doc_id FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    return get_related(doc_id, limit=limit)


@router.get("/docs/{doc_id}/coordinates",
            summary="Get Daenary semantic coordinates for a document")
def get_doc_coordinates(doc_id: str):
    """Returns the Daenary dimension coordinates indexed for a document.

    Phase 8 addition. Returns empty list for docs without daenary: frontmatter.
    """
    doc = db.fetchone("SELECT doc_id FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    coords = get_coordinates(doc_id)
    return {
        "doc_id": doc_id,
        "coordinates": coords,
        "summary": format_coordinate_summary(coords) if coords else None,
        "count": len(coords),
    }


@router.get("/graph",
            summary="Graph data for Atlas visualization (nodes + edges)")
def get_graph(
    max_nodes: int = Query(200, ge=10, le=500),
):
    """Returns all documents as nodes and relationships as edges.

    Phase 8: edges sourced from explicit doc_edges (DCNS) first, then lineage,
    then optional topic-similarity pairs.
    Node payload includes DCNS diagnostics (load_score, conflict_count, etc.)
    """
    return get_graph_data(max_nodes=max_nodes)


@router.post("/dcns/sync",
             summary="Rebuild DCNS doc_edges from lineage and conflicts")
def dcns_sync():
    """Rebuilds the doc_edges table from lineage records and conflicts.

    Safe to call at any time — idempotent via INSERT OR REPLACE.
    """
    from app.core.dcns import sync_edges
    result = sync_edges()
    return {"status": "ok", **result}

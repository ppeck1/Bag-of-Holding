"""app/api/routes/reader.py: Document reader and graph endpoints for Bag of Holding v2.

Phase 7 — Blueprint implementation:
  GET /api/docs/{id}/content  — raw markdown body (frontmatter stripped)
  GET /api/docs/{id}/related  — semantically related documents
  GET /api/graph              — full graph data (nodes + edges) for Atlas visualization

Phase 8 — Daenary + DCNS additions:
  GET /api/docs/{id}/coordinates  — Daenary coordinate dimensions for a document
  POST /api/dcns/sync             — rebuild doc_edges from lineage + conflicts
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.db import connection as db
from app.services.parser import parse_frontmatter_full
from app.core.related import get_related, get_graph_data
from app.core.visual_projection import get_projection_graph
from app.core.daenary import get_coordinates, format_coordinate_summary
from app.core.folded_node import build_folded_node_packet
from app.core.auth import require_operator
from app.core.fs_boundary import (
    PathBoundaryViolation,
    get_library_root,
    resolve_under_library,
)

router = APIRouter(prefix="/api")

def _resolve_doc_path(doc: dict):
    """Resolve doc path relative to the server-owned library root only."""
    return resolve_under_library(doc["path"] or "")


@router.get("/docs/{doc_id}/content",
            response_class=PlainTextResponse,
            summary="Get raw markdown body of a document (frontmatter stripped)")
def get_doc_content(doc_id: str, library_root: Optional[str] = Query(None)):
    """Returns the markdown body text of a document, with YAML frontmatter removed.

    Used by the client-side markdown renderer.
    Returns 404 if document not found or file not on disk.
    """
    doc = db.fetchone("SELECT path, corpus_class FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    # WO-2 audit item 2: raw-content access to promoted docs is env-gated (fail-closed) —
    # this route would otherwise bypass the promoted-exposure predicate entirely.
    from app.core import promoted_exposure
    if promoted_exposure.is_promoted_row(doc) and not promoted_exposure.env_gate_open():
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    if library_root:
        raise HTTPException(status_code=403, detail="caller-supplied library_root is not allowed")
    try:
        full_path = _resolve_doc_path(doc)
    except PathBoundaryViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"File not found on disk: {doc['path']} (library root: {get_library_root()})"
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


@router.get("/docs/{doc_id}/fold",
            summary="Read-only folded-node packet for Atlas facets")
def get_doc_fold(doc_id: str):
    """Return a compact, read-only packet for expanding a graph node in place."""
    packet = build_folded_node_packet(doc_id)
    if not packet:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return packet


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
    Phase 11: edges enriched with reasons, shared_topics, crossovers.
    Node payload includes DCNS diagnostics (load_score, conflict_count, etc.)
    """
    return get_graph_data(max_nodes=max_nodes)


@router.get("/graph/projection",
            summary="Projection-ready graph data for Atlas visualization")
def get_graph_projection(
    mode: str = Query("web", pattern="^(web|structural|constitutional|constraint|geometry|constraint-geometry|variable)$"),
    max_nodes: int = Query(300, ge=10, le=500),
):
    """Returns deterministic, mode-aware graph coordinates and diagnostics."""
    return get_projection_graph(mode=mode, max_nodes=max_nodes)


@router.get("/graph/neighborhood",
            summary="Local neighborhood subgraph for a document node")
def get_neighborhood(
    doc_id: str = Query(...),
    depth:  int = Query(1, ge=1, le=2),
    limit:  int = Query(40, ge=5, le=80),
):
    """Return the local subgraph centred on doc_id for neighborhood expansion.

    depth=1 — direct neighbors only
    depth=2 — neighbors of neighbors (limit aggressively applied)
    Edges include reasons, shared_topics, crossovers for strand tooltips.
    """
    from app.core.related import get_neighborhood
    result = get_neighborhood(doc_id, depth=depth, limit=limit)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/dcns/sync",
             summary="Rebuild DCNS doc_edges from lineage and conflicts")
def dcns_sync(_operator: str = Depends(require_operator)):
    """Rebuilds the doc_edges table from lineage records and conflicts.

    Safe to call at any time — idempotent via INSERT OR REPLACE.
    """
    from app.core.dcns import sync_edges
    result = sync_edges()
    return {"status": "ok", **result}

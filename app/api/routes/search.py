"""app/api/routes/search.py: Search API endpoint for Bag of Holding v2.

Phase 8 additions: optional Daenary filter parameters.
"""
from typing import Optional
from fastapi import APIRouter, Query
from app.core import search as search_engine

router = APIRouter(prefix="/api")

@router.get("/search", summary="Full-text search with explainable scoring")
def search(
    q: str = Query(..., description="Search query"),
    plane: Optional[str] = Query(None, description="Filter by plane_scope path"),
    limit: int = Query(20, ge=1, le=100),
    # Phase 8: Daenary filters
    dimension: Optional[str] = Query(None, description="Filter by Daenary dimension name"),
    state: Optional[int] = Query(None, description="Filter by Daenary state (-1, 0, or 1)", ge=-1, le=1),
    min_quality: Optional[float] = Query(None, description="Minimum Daenary quality [0,1]", ge=0.0, le=1.0),
    min_confidence: Optional[float] = Query(None, description="Minimum Daenary confidence [0,1]", ge=0.0, le=1.0),
    stale: bool = Query(False, description="Return only docs with expired valid_until"),
    uncertain_only: bool = Query(False, description="Return only state=0/contain docs (high-signal, low-certainty)"),
    conflicts_only: bool = Query(False, description="Return only docs with open conflicts"),
):
    results = search_engine.search(
        q,
        plane_filter=plane,
        limit=limit,
        dimension=dimension,
        state=state,
        min_quality=min_quality,
        min_confidence=min_confidence,
        stale=stale,
        uncertain_only=uncertain_only,
        conflicts_only=conflicts_only,
    )
    active_daenary_filters = {
        k: v for k, v in {
            "dimension": dimension, "state": state, "min_quality": min_quality,
            "min_confidence": min_confidence, "stale": stale,
            "uncertain_only": uncertain_only, "conflicts_only": conflicts_only,
        }.items() if v is not None and v is not False
    }
    return {
        "query": q,
        "plane_filter": plane,
        "count": len(results),
        "results": results,
        "score_formula": "0.6*text_score + 0.2*canon_score + 0.2*planar_alignment + conflict_penalty + daenary_adjustment",
        "daenary_filters": active_daenary_filters or None,
    }

"""app/api/routes/review.py: Document analysis artifact endpoints.

Phase 26.5 additions:
  GET  /api/review               — query-param route (preferred; handles nested paths)
  GET  /api/review/{doc_path}    — legacy path-param route (kept for backwards compat)
  POST /api/review/{doc_path}/regenerate — force regeneration
  GET  /api/analysis/status      — pipeline health summary (Fix H)
"""
import os
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from app.services import reviewer as llm_review
from app.core.auth import OPERATOR_HEADER, require_operator
from app.core.document_analysis_pipeline import get_analysis_status
from app.core.fs_boundary import get_library_root

router = APIRouter(prefix="/api")
LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")


def _server_library_root(library_root: Optional[str] = None) -> str:
    if library_root:
        raise HTTPException(status_code=403, detail="caller-supplied library_root is not allowed")
    return str(get_library_root())


def _require_generation_operator(token: Optional[str]) -> None:
    require_operator(x_boh_operator_token=token)


@router.get("/review",
            summary="Phase 26.5 Fix F: Load or generate review artifact via query param (preferred)")
def get_review_by_query(
    path: str = Query(..., description="Library-relative path to the document"),
    force: bool = Query(False, description="Force regeneration even if artifact exists"),
    library_root: Optional[str] = Query(None),
    x_boh_operator_token: Optional[str] = Header(default=None, alias=OPERATOR_HEADER),
):
    """Load or generate a deterministic review artifact.

    Uses query param ?path= to avoid FastAPI path-param slash encoding issues.
    If force=true, regenerates the artifact even if one exists on disk.

    Always non-authoritative. All patches require explicit user confirmation.
    """
    root = _server_library_root(library_root)

    if force:
        _require_generation_operator(x_boh_operator_token)
        artifact = llm_review.generate_review_artifact(path, root)
        if "error" in artifact:
            raise HTTPException(status_code=404, detail=artifact["error"])
        artifact["_status"] = "regenerated"
        return artifact

    existing = llm_review.load_review_artifact(path, root)
    if existing:
        existing["_status"] = "existing"
        return existing

    _require_generation_operator(x_boh_operator_token)
    artifact = llm_review.generate_review_artifact(path, root)
    if "error" in artifact:
        raise HTTPException(status_code=404, detail=artifact["error"])
    artifact["_status"] = "generated"
    return artifact


@router.get("/review/{doc_path:path}",
            summary="Load existing review artifact or generate if missing (legacy path-param route)")
def get_review(doc_path: str, library_root: Optional[str] = Query(None),
               force: bool = Query(False),
               x_boh_operator_token: Optional[str] = Header(default=None, alias=OPERATOR_HEADER)):
    """Legacy path-param route. Prefer GET /api/review?path=... for new callers."""
    root = _server_library_root(library_root)

    if force:
        _require_generation_operator(x_boh_operator_token)
        artifact = llm_review.generate_review_artifact(doc_path, root)
        if "error" in artifact:
            raise HTTPException(status_code=404, detail=artifact["error"])
        artifact["_status"] = "regenerated"
        return artifact

    existing = llm_review.load_review_artifact(doc_path, root)
    if existing:
        existing["_status"] = "existing"
        return existing

    _require_generation_operator(x_boh_operator_token)
    artifact = llm_review.generate_review_artifact(doc_path, root)
    if "error" in artifact:
        raise HTTPException(status_code=404, detail=artifact["error"])
    artifact["_status"] = "generated"
    return artifact


@router.post("/review/{doc_path:path}/regenerate",
             summary="Force-regenerate the review artifact (non-authoritative)")
def regenerate_review(doc_path: str, library_root: Optional[str] = Query(None),
                      _operator: str = Depends(require_operator)):
    """Force regenerates the review artifact, overwriting any existing one."""
    root = _server_library_root(library_root)
    artifact = llm_review.generate_review_artifact(doc_path, root)
    if "error" in artifact:
        raise HTTPException(status_code=404, detail=artifact["error"])
    artifact["_status"] = "regenerated"
    return artifact


@router.get("/analysis/status",
            summary="Phase 26.5 Fix H: Analysis pipeline status — deterministic review + LLM state")
def get_analysis_pipeline_status(library_root: Optional[str] = Query(None)):
    """Return the analysis pipeline health summary.

    Shows:
        deterministic_review: artifact counts, missing artifacts, total docs
        llm: enabled state, invocations, queue depth
        last_analysis_events: recent document_analysis_* audit events

    This makes it impossible to confuse 'analysis failed' with 'analysis never ran'.
    """
    root = _server_library_root(library_root)
    return get_analysis_status(library_root=root)

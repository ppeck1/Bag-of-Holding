"""app/api/routes/review.py: LLM review artifact endpoints for Bag of Holding v2.

Phase 9 additions:
  GET  /api/review/{doc_path}            — load existing artifact if present, generate if missing
  POST /api/review/{doc_path}/regenerate — force regeneration regardless of existing artifact
"""
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services import reviewer as llm_review

router = APIRouter(prefix="/api")
LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")


@router.get("/review/{doc_path:path}",
            summary="Load existing review artifact or generate if missing (non-authoritative)")
def get_review(doc_path: str, library_root: Optional[str] = Query(None)):
    """Returns the review artifact for a document.

    If an artifact already exists on disk, returns it without regenerating.
    If no artifact exists, generates one and writes it to disk.

    Always non-authoritative. All patches require explicit user confirmation.
    """
    root = library_root or LIBRARY_ROOT

    # Try to load existing artifact first
    existing = llm_review.load_review_artifact(doc_path, root)
    if existing:
        existing["_status"] = "existing"
        return existing

    # No artifact — generate fresh
    artifact = llm_review.generate_review_artifact(doc_path, root)
    if "error" in artifact:
        raise HTTPException(status_code=404, detail=artifact["error"])
    artifact["_status"] = "generated"
    return artifact


@router.post("/review/{doc_path:path}/regenerate",
             summary="Force-regenerate the review artifact (non-authoritative)")
def regenerate_review(doc_path: str, library_root: Optional[str] = Query(None)):
    """Force regenerates the review artifact, overwriting any existing one.

    Always non-authoritative. All patches require explicit user confirmation.
    """
    root = library_root or LIBRARY_ROOT
    artifact = llm_review.generate_review_artifact(doc_path, root)
    if "error" in artifact:
        raise HTTPException(status_code=404, detail=artifact["error"])
    artifact["_status"] = "regenerated"
    return artifact

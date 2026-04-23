"""app/api/routes/review.py"""
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services import reviewer as llm_review

router = APIRouter(prefix="/api")
LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")

@router.get("/review/{doc_path:path}", summary="Generate LLM review artifact (non-authoritative)")
def generate_review(doc_path: str, library_root: Optional[str] = Query(None)):
    root = library_root or LIBRARY_ROOT
    artifact = llm_review.generate_review_artifact(doc_path, root)
    if "error" in artifact:
        raise HTTPException(status_code=404, detail=artifact["error"])
    return artifact

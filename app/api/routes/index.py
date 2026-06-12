"""app/api/routes/index.py: Index route for Bag of Holding v2."""

import os
from fastapi import APIRouter, Depends, HTTPException
from app.api.models import IndexRequest
from app.services import indexer as crawler
from app.core import conflicts as conflict_engine
from app.core.auth import require_operator
from app.core.fs_boundary import PathBoundaryViolation, ensure_request_root_allowed

router = APIRouter(prefix="/api")
LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")


@router.post("/index", summary="Index the filesystem library")
def index_library(req: IndexRequest = None, _operator: str = Depends(require_operator)):
    requested = req.library_root if req and req.library_root else None
    try:
        root = ensure_request_root_allowed(requested, LIBRARY_ROOT)
    except PathBoundaryViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    result = crawler.crawl_library(root)
    new_conflicts = conflict_engine.detect_all_conflicts()
    result["conflicts_detected"] = len(new_conflicts)
    result["new_conflicts"] = new_conflicts
    return result

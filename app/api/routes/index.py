"""app/api/routes/index.py: Index route for Bag of Holding v2."""

import os
from fastapi import APIRouter
from app.api.models import IndexRequest
from app.services import indexer as crawler
from app.core import conflicts as conflict_engine

router = APIRouter(prefix="/api")
LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")


@router.post("/index", summary="Index the filesystem library")
def index_library(req: IndexRequest = None):
    root = (req.library_root if req and req.library_root else None) or LIBRARY_ROOT
    result = crawler.crawl_library(root)
    new_conflicts = conflict_engine.detect_all_conflicts()
    result["conflicts_detected"] = len(new_conflicts)
    result["new_conflicts"] = new_conflicts
    return result

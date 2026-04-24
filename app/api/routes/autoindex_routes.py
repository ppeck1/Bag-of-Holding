"""app/api/routes/autoindex_routes.py: Auto-index API endpoints for Phase 12.

GET  /api/autoindex/status  — current auto-index state
POST /api/autoindex/run     — trigger a manual index run
"""

import os
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import autoindex

router = APIRouter(prefix="/api")

LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")


class AutoIndexRequest(BaseModel):
    library_root: Optional[str] = None
    max_files: int = 5000
    changed_only: bool = True


@router.get("/autoindex/status", summary="Get auto-index state", tags=["system"])
def get_autoindex_status():
    return autoindex.get_status()


@router.post("/autoindex/run", summary="Trigger a library index run", tags=["system"])
def trigger_autoindex(req: AutoIndexRequest):
    """Scan and index the library. Skips unchanged files when changed_only=True."""
    # Read env at request time so environment overrides always take effect
    root = req.library_root or os.environ.get("BOH_LIBRARY", "./library")
    result = autoindex.run_auto_index(
        library_root=root,
        max_files=req.max_files,
        changed_only=req.changed_only,
    )
    return result

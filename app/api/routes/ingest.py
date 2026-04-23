"""app/api/routes/ingest.py: Snapshot ingest route for Bag of Holding v2.

Phase 2: Closes v0P gap — snapshot ingest now has an HTTP endpoint.
See docs/corpus_migration_doctrine.md §3b for ingest rules.
"""

from pydantic import BaseModel
from fastapi import APIRouter
from app.core import snapshot as snapshot_engine

router = APIRouter(prefix="/api")


class SnapshotIngestRequest(BaseModel):
    path: str  # absolute or relative path to boh_export_*.json


@router.post("/ingest/snapshot", summary="Ingest a BOH_WORKER snapshot export file")
def ingest_snapshot(req: SnapshotIngestRequest):
    """Load a boh_export_<run_id>.json file and populate the database.

    Canon guard: incoming docs that match an existing canonical doc_id are
    skipped and reported — never silently overwritten.
    D2: Events without explicit start + timezone are skipped.
    Returns full ingest summary including skipped entries.
    """
    return snapshot_engine.ingest_snapshot_export(req.path)

"""app/api/routes/execution_routes.py: Code execution endpoints for Bag of Holding v2.

Phase 10 addition.

  POST /api/exec/run          — run a code block (Python or shell)
  GET  /api/exec/runs/{doc_id} — list runs for a document
  GET  /api/exec/run/{run_id} — fetch a single run + artifacts
  GET  /api/exec/artifact/{artifact_id} — fetch artifact content
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import execution

router = APIRouter(prefix="/api")


class RunRequest(BaseModel):
    doc_id:         str
    block_id:       str
    language:       str
    code:           str
    executor:       str = "human"
    workspace_path: Optional[str] = None
    entity_type:    str = "human"   # for permission check
    entity_id:      str = "*"


@router.post("/exec/run", summary="Execute a code block (Python or shell)")
def run_block(req: RunRequest):
    """Execute a code block and return the run result with full lineage.

    Enforcement:
      - Safety denylist check (shell + python)
      - execute permission check (entity_type/entity_id on workspace)
      - Workspace path restricted to library root (no path traversal)

    Supports: python, shell. Every run is recorded as an exec_run record.
    """
    library_root = os.environ.get("BOH_LIBRARY", "./library")
    result = execution.run_block(
        doc_id=req.doc_id,
        block_id=req.block_id,
        language=req.language,
        code=req.code,
        executor=req.executor,
        workspace_path=req.workspace_path,
        library_root=library_root,
        entity_type=req.entity_type,
        entity_id=req.entity_id,
    )
    if result.get("error") and not result.get("run_id"):
        status = 403 if result.get("permission_denied") else 400
        raise HTTPException(status_code=status, detail=result["error"])
    return result


@router.get("/exec/runs/{doc_id}", summary="List execution runs for a document")
def list_runs(doc_id: str, limit: int = 20):
    """Return recent execution runs for a document, newest first."""
    return {
        "doc_id": doc_id,
        "runs": execution.list_runs(doc_id, limit=limit),
        "count": len(execution.list_runs(doc_id, limit=limit)),
    }


@router.get("/exec/run/{run_id}", summary="Fetch a single execution run with artifacts")
def get_run(run_id: str):
    """Return the full run record including stdout, stderr, and artifact list."""
    run = execution.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@router.get("/exec/artifact/{artifact_id}", summary="Fetch artifact content")
def get_artifact(artifact_id: str):
    """Return an execution artifact by ID, including its inline content."""
    art = execution.get_artifact_content(artifact_id)
    if not art:
        raise HTTPException(status_code=404,
                            detail=f"Artifact {artifact_id} not found")
    return art

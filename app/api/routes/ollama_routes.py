"""app/api/routes/ollama_routes.py: Local LLM (Ollama) endpoints for Bag of Holding v2.

Phase 10 addition.

  GET  /api/ollama/health                — check Ollama availability
  GET  /api/ollama/models                — list available models
  POST /api/ollama/invoke                — run a task-scoped invocation
  GET  /api/ollama/invocations           — list recent invocations
  GET  /api/ollama/invocation/{id}       — fetch a single invocation
  GET  /api/ollama/tasks                 — list valid task types
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core import ollama

router = APIRouter(prefix="/api")


class InvokeRequest(BaseModel):
    task_type:  str
    content:    str
    model:      Optional[str] = None
    doc_id:     Optional[str] = None
    scope:      Optional[dict] = None
    timeout:    int = 60


@router.get("/ollama/health", summary="Check Ollama service availability")
def ollama_health():
    """Returns whether Ollama is reachable and which models are available."""
    return ollama.health_check()


@router.get("/ollama/models", summary="List available Ollama models")
def ollama_models():
    """Returns list of model names available from the configured Ollama endpoint."""
    return {"models": ollama.list_models()}


@router.get("/ollama/tasks", summary="List valid task types for LLM invocation")
def ollama_tasks():
    """Returns the set of supported task_type values."""
    return {
        "task_types": sorted(ollama.TASK_TYPES),
        "note": "All outputs are non-authoritative. Human confirmation required for any action.",
    }


@router.post("/ollama/invoke", summary="Run a task-scoped LLM invocation")
def ollama_invoke(req: InvokeRequest):
    """Execute a structured LLM task against a local Ollama model.

    Every invocation is recorded in llm_invocations for audit.
    All outputs are non_authoritative=True and require explicit confirmation.
    Models cannot write to canon directly.
    """
    result = ollama.invoke(
        task_type=req.task_type,
        content=req.content,
        model=req.model,
        doc_id=req.doc_id,
        scope=req.scope,
        timeout=req.timeout,
    )
    if result.get("error") and not result.get("invocation_id"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/ollama/invocations", summary="List recent LLM invocations")
def list_invocations(
    doc_id:    Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    limit:     int           = Query(20, ge=1, le=100),
):
    """Return recent LLM invocations, optionally filtered by doc or task type."""
    return {
        "invocations": ollama.list_invocations(doc_id=doc_id,
                                                task_type=task_type,
                                                limit=limit),
    }


@router.get("/ollama/invocation/{invocation_id}",
            summary="Fetch a single LLM invocation record")
def get_invocation(invocation_id: str):
    """Return the full invocation record including response text and parsed JSON."""
    inv = ollama.get_invocation(invocation_id)
    if not inv:
        raise HTTPException(status_code=404,
                            detail=f"Invocation {invocation_id} not found")
    return inv

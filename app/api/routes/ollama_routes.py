"""app/api/routes/ollama_routes.py: Local LLM (Ollama) endpoints for Bag of Holding v2.

Phase 10 addition. Phase 12.H hardening:
  - /api/ollama/invoke returns 503 unless BOH_OLLAMA_ENABLED=true
  - timeout Field capped to [1, 120]
  - content size validated (≤ 20,000 chars) before hitting core
  - health/models/tasks remain accessible regardless of enabled flag

  GET  /api/ollama/health                — check Ollama availability
  GET  /api/ollama/models                — list available models
  POST /api/ollama/invoke                — run a task-scoped invocation (requires BOH_OLLAMA_ENABLED=true)
  GET  /api/ollama/invocations           — list recent invocations
  GET  /api/ollama/invocation/{id}       — fetch a single invocation
  GET  /api/ollama/tasks                 — list valid task types
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core import ollama

router = APIRouter(prefix="/api")

_MAX_CONTENT_CHARS: int = int(os.environ.get("BOH_OLLAMA_MAX_CONTENT", "20000"))


class InvokeRequest(BaseModel):
    task_type: str
    content:   str
    model:     Optional[str]  = None
    doc_id:    Optional[str]  = None
    scope:     Optional[dict] = None
    # Fix 2: timeout bounded at the Pydantic layer — never reaches core unbounded
    timeout:   int = Field(30, ge=1, le=120)


@router.get("/ollama/health", summary="Check Ollama service availability")
def ollama_health():
    """Returns whether Ollama is reachable and which models are available.
    Always accessible — not gated by BOH_OLLAMA_ENABLED.
    """
    return ollama.health_check()


@router.get("/ollama/models", summary="List available Ollama models")
def ollama_models():
    """Returns list of model names. Not gated by BOH_OLLAMA_ENABLED."""
    return {"models": ollama.list_models()}


@router.get("/ollama/tasks", summary="List valid task types for LLM invocation")
def ollama_tasks():
    return {
        "task_types": sorted(ollama.TASK_TYPES),
        "note": "All outputs are non-authoritative. Human confirmation required for any action.",
    }


@router.post("/ollama/invoke", summary="Run a task-scoped LLM invocation")
def ollama_invoke(req: InvokeRequest):
    """Execute a structured LLM task against a local Ollama model.

    Fix 1: Returns 503 Service Unavailable if BOH_OLLAMA_ENABLED != 'true'.
    Fix 2: timeout already bounded by Field(ge=1, le=120).
    Fix 3: content size rejected at route layer before hitting core.

    Every invocation is recorded in llm_invocations for audit.
    All outputs are non_authoritative=True and require explicit confirmation.
    Models cannot write to canon directly.
    """
    # Fix 1 — 503 guard at route level (belt-and-suspenders with core check)
    if not ollama._is_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "Ollama integration is disabled. "
                "Set BOH_OLLAMA_ENABLED=true to enable LLM features."
            ),
        )

    # Fix 3 — content size gate at route level
    if len(req.content) > _MAX_CONTENT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Content too large: {len(req.content)} chars "
                f"(limit {_MAX_CONTENT_CHARS}). "
                "Reduce content length or set BOH_OLLAMA_MAX_CONTENT to override."
            ),
        )

    result = ollama.invoke(
        task_type=req.task_type,
        content=req.content,
        model=req.model,
        doc_id=req.doc_id,
        scope=req.scope,
        timeout=req.timeout,
    )

    # Propagate 503 from core if enabled flag changed between checks
    if result.get("disabled"):
        raise HTTPException(status_code=503, detail=result["error"])

    # Propagate rejected scope dirs
    if result.get("rejected_dirs") is not None:
        raise HTTPException(status_code=422, detail=result["error"])

    if result.get("content_too_large"):
        raise HTTPException(status_code=422, detail=result["error"])

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


@router.get("/ollama/invocations", summary="List recent LLM invocations")
def list_invocations(
    doc_id:    Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    limit:     int           = Query(20, ge=1, le=100),
):
    return {
        "invocations": ollama.list_invocations(
            doc_id=doc_id, task_type=task_type, limit=limit
        ),
    }


@router.get(
    "/ollama/invocation/{invocation_id}",
    summary="Fetch a single LLM invocation record",
)
def get_invocation(invocation_id: str):
    inv = ollama.get_invocation(invocation_id)
    if not inv:
        raise HTTPException(
            status_code=404,
            detail=f"Invocation {invocation_id} not found",
        )
    return inv

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
    # Phase 14: Validate task type first (always, regardless of enabled state)
    if req.task_type not in ollama.TASK_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown task_type: {req.task_type!r}. Valid: {sorted(ollama.TASK_TYPES)}")

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

    # Disabled: core returns structured response with invocation_id — pass through
    if result.get("disabled"):
        return result

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


# ── Ollama enable/disable toggle ──────────────────────────────────────────────
from pydantic import BaseModel as _BM

class OllamaToggleRequest(_BM):
    enabled: bool


@router.get("/ollama/enabled", summary="Get Ollama enabled state", tags=["ollama"])
def get_ollama_enabled():
    """Returns whether Ollama is enabled (UI-controlled toggle, DB-persisted)."""
    from app.db import connection as _db
    row = _db.fetchone("SELECT value FROM system_config WHERE key = 'ollama_enabled'")
    env_enabled = ollama._is_enabled()
    db_enabled  = (row["value"] == "true") if row else False
    return {
        "enabled": db_enabled or env_enabled,
        "db_enabled": db_enabled,
        "env_enabled": env_enabled,
        "source": "env" if env_enabled else ("db" if db_enabled else "none"),
    }


@router.post("/ollama/enabled", summary="Enable or disable Ollama via UI toggle", tags=["ollama"])
def set_ollama_enabled(req: OllamaToggleRequest):
    """Toggle Ollama on/off from the UI. Persisted in system_config table.
    Does not require editing environment variables or restarting the server.
    """
    import time as _time
    from app.db import connection as _db
    val = "true" if req.enabled else "false"
    _db.execute(
        "INSERT OR REPLACE INTO system_config (key, value, updated_ts) VALUES ('ollama_enabled', ?, ?)",
        (val, int(_time.time())),
    )
    return {
        "ok": True,
        "enabled": req.enabled,
        "message": f"Ollama {'enabled' if req.enabled else 'disabled'} (persisted in DB).",
    }

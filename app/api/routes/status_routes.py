"""app/api/routes/status_routes.py: System status diagnostics for Phase 12.

GET /api/status  — full system health snapshot
"""

import os
from pathlib import Path

from fastapi import APIRouter

from app.db import connection as db
from app.core import autoindex, llm_queue

router = APIRouter(prefix="/api")


@router.get("/status", summary="System status diagnostics", tags=["system"])
def get_system_status():
    library_root  = os.environ.get("BOH_LIBRARY", "./library")
    library_found = Path(library_root).expanduser().resolve().exists()

    # Doc counts
    try:
        indexed_docs = db.fetchone("SELECT COUNT(*) AS n FROM docs")["n"]
    except Exception:
        indexed_docs = 0

    # Edge counts (explicit + lineage)
    try:
        explicit_edges = db.fetchone("SELECT COUNT(*) AS n FROM doc_edges")["n"]
        lineage_edges  = db.fetchone("SELECT COUNT(*) AS n FROM lineage")["n"]
        graph_edges    = explicit_edges + lineage_edges
    except Exception:
        graph_edges = 0

    # Failed-index count from audit log
    try:
        err_row = db.fetchone(
            "SELECT COUNT(*) AS n FROM audit_log "
            "WHERE event_type='index' AND detail LIKE '%\"failed\": [1-9]%'"
        )
        index_errors = err_row["n"] if err_row else 0
    except Exception:
        index_errors = 0

    # Pending review items
    try:
        pending_reviews = llm_queue.get_pending_count()
    except Exception:
        pending_reviews = 0

    # Auto-index state
    try:
        ai_status = autoindex.get_status()
    except Exception:
        ai_status = {"last_run_ts": None, "last_indexed": 0}

    # Ollama. Use the same DB-or-env gate as the Ollama routes so the
    # Status panel reflects the UI toggle immediately.
    try:
        from app.core.ollama import health_check, OLLAMA_URL, DEFAULT_MODEL, _is_enabled
        ollama_enabled = _is_enabled()
        hc = health_check() if ollama_enabled else {"available": False}
        ollama_info = {
            "enabled":   ollama_enabled,
            "available": hc.get("available", False),
            "model":     DEFAULT_MODEL,
            "url":       OLLAMA_URL,
        }
    except Exception:
        ollama_info = {"enabled": False, "available": False, "model": None}

    try:
        from app.core.governance_metrics import governance_native_metrics
        gov_metrics = governance_native_metrics(limit=10).get("primary_metrics", {})
    except Exception:
        gov_metrics = {}

    return {
        "server":         "ok",
        "primary_status_surface": "/api/integrity/dashboard",
        "governance_native_metrics": gov_metrics,
        "phase":          12,
        "library_root":   library_root,
        "library_found":  library_found,
        "indexed_docs":   indexed_docs,
        "graph_edges":    graph_edges,
        "last_indexed_at": ai_status.get("last_run_ts"),
        "ollama":         ollama_info,
        "review_queue":   {"pending": pending_reviews},
        "index_errors":   index_errors,
        "autoindex":      ai_status,
    }

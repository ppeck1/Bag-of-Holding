"""app/api/main.py: FastAPI application factory for Bag of Holding v2.

Phase 3: SPA served from app/ui/ via StaticFiles.
All /api/* routes registered before the static mount.
Phase 12: auto-index on startup, lifecycle routes, status, LLM queue.
"""

import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import connection as db
from app.api.routes import (
    index, search, canon, conflicts,
    library, workflow, nodes, events,
    review, ingest, dashboard, lineage, reader,
    authoring, execution_routes, ollama_routes, governance_routes,
    input_routes,
)
# Phase 12 routes
from app.api.routes import (
    lifecycle_routes,
    status_routes,
    llm_queue_routes,
    autoindex_routes,
    approval_routes,   # Phase 15: explicit governance workflow
)
# Phase 19: PCDS Plane Card routes
from app.api.routes.plane_routes import router as plane_router, doc_card_router
# Phase 20: Certificate Gate + Constraint Lattice
from app.api.routes.certificate_routes import router as certificate_router
from app.api.routes.plane_interface_routes import router as plane_interface_router
from app.api.routes.lattice_routes import router as lattice_router
from app.api.routes.feedback_routes import router as feedback_router
from app.api.routes.coherence_routes import router as coherence_router
from app.api.routes.temporal_governor_routes import router as temporal_governor_router
from app.api.routes.authority_routes import router as authority_router
from app.api.routes.escalation_routes import router as escalation_router
from app.api.routes.integrity_routes import router as integrity_router
from app.api.routes.governance_metrics_routes import router as governance_metrics_router
from app.api.routes.substrate_routes import router as substrate_router
from app.api.routes.workspace_routes import router as workspace_router


# ── Init ──────────────────────────────────────────────────────────────────────
db.init_db()


# ── Lifespan: auto-index on startup ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run auto-index in background on startup when BOH_AUTO_INDEX=true.
    Runs in a daemon thread — server startup is never blocked.
    Errors inside run_on_startup_if_enabled() are caught and logged.
    """
    from app.core.autoindex import run_on_startup_if_enabled
    t = threading.Thread(target=run_on_startup_if_enabled, daemon=True)
    t.start()
    yield
    # shutdown: nothing to teardown


def _get_cors_origins() -> list[str]:
    """Localhost-only by default; override with BOH_CORS_ORIGINS=url1,url2."""
    env = os.environ.get("BOH_CORS_ORIGINS", "")
    if env.strip():
        return [o.strip() for o in env.split(",") if o.strip()]
    return [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


app = FastAPI(
    title="Bag of Holding v2",
    description=(
        "Deterministic Local Knowledge Workbench — "
        "Planar Math + Rubrix Governance. "
        "Local-first. No auto-resolution. Explainable scoring."
    ),
    version="2.12.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # BOH is a local-first tool. Restrict to localhost by default.
    # Override at deployment by setting BOH_CORS_ORIGINS=https://... (comma-separated).
    allow_origins=_get_cors_origins(),
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

# ── API routers — registered BEFORE static mount ──────────────────────────────
for router in (
    index.router,
    search.router,
    canon.router,
    conflicts.router,
    library.router,
    workflow.router,
    nodes.router,
    events.router,
    review.router,
    ingest.router,
    dashboard.router,
    lineage.router,
    reader.router,
    authoring.router,
    execution_routes.router,
    ollama_routes.router,
    governance_routes.router,
    input_routes.router,
    # Phase 12
    lifecycle_routes.router,
    status_routes.router,
    llm_queue_routes.router,
    autoindex_routes.router,
    approval_routes.router,    # Phase 15
    plane_router,              # Phase 19: Plane Cards
    doc_card_router,           # Phase 19: /api/docs/{id}/card
    certificate_router,        # Phase 20: Certificate Gate
    plane_interface_router,    # Phase 21: Plane Interfaces
    lattice_router,            # Phase 22: Constraint-native lattice graph
    feedback_router,           # Phase 23: Feedback rewrite engine
    coherence_router,          # Phase 24: Coherence decay + refresh engine
    temporal_governor_router,    # Phase 24.2: Temporal Coherence Governor
    authority_router,            # Phase 24.3: Authority Enforcement
    escalation_router,           # Phase 24.3: Temporal Escalation Ladder
    integrity_router,            # Phase 24.3: Integrity-First Surface
    governance_metrics_router,   # Phase 25.1: Governance-native metrics
    substrate_router,            # Phase 25: Substrate Lattice
    workspace_router,            # Phase 26.3: Workspace reset + fixture seeding
):
    app.include_router(router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/api/health", summary="Service health check", tags=["system"])
def health():
    library_root = os.environ.get("BOH_LIBRARY", "./library")
    try:
        db.fetchone("SELECT 1")
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"
    return {
        "status":  "ok",
        "version": "2.0.0",
        "phase":   12,
        "db":      db_status,
        "library": library_root,
    }


# ── SPA static files — mounted LAST so /api/* routes take priority ────────────
_ui_dir = Path(__file__).parent.parent / "ui"
_vendor_dir = _ui_dir / "vendor"
if _vendor_dir.exists():
    # Serve vendor libraries (KaTeX, marked.js) at /vendor/ before the root SPA mount
    app.mount("/vendor", StaticFiles(directory=str(_vendor_dir)), name="vendor")
if _ui_dir.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dir), html=True), name="ui")

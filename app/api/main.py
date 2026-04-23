"""app/api/main.py: FastAPI application factory for Bag of Holding v2.

Phase 3: SPA served from app/ui/ via StaticFiles.
All /api/* routes registered before the static mount.
"""

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import connection as db
from app.api.routes import (
    index, search, canon, conflicts,
    library, workflow, nodes, events,
    review, ingest, dashboard, lineage, reader,
)

# ── Init ──────────────────────────────────────────────────────────────────────
db.init_db()

app = FastAPI(
    title="Bag of Holding v2",
    description=(
        "Deterministic Local Knowledge Workbench — "
        "Planar Math + Rubrix Governance. "
        "Local-first. No auto-resolution. Explainable scoring."
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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
        "status": "ok",
        "version": "2.0.0",
        "phase": 7,
        "db": db_status,
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

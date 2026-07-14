"""app/api/main.py: FastAPI application factory for Bag of Holding v2.

Phase 3: SPA served from app/ui/ via StaticFiles.
All /api/* routes registered before the static mount.
Phase 12: auto-index on startup, lifecycle routes, status, LLM queue.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import connection as db
from app.core.auth import require_operator, operator_status
from app.core.fs_boundary import PathBoundaryViolation, resolve_under_library
from app.core.version import APP_VERSION, STATUS_LABEL, SYSTEM_PHASE
from app.api.routes import (
    index, search, canon, conflicts,
    library, libraries, workflow, nodes, events,
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
from app.api.routes.actor_routes import router as actor_router
from app.api.routes.retrieval_routes import router as retrieval_router
from app.api.routes.intake_routes import router as intake_router
from app.api.routes.fold_routes import router as fold_router
from app.api.routes.trace_routes import router as trace_router
from app.api.routes.review_queue_routes import router as review_queue_router
from app.api.routes.residence_routes import router as residence_router
from app.api.routes.context_pack_routes import router as context_pack_router
from app.api.routes.context_object_routes import router as context_object_router
from app.api.routes.current_context_brief_routes import router as current_context_brief_router
from app.api.routes.security_settings_routes import router as security_settings_router


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
    from app.services.intake import scheduler_manager
    scheduler_manager.start_if_enabled()
    # Auto-seed productivity methods demo library if zip is available and not yet seeded
    def _auto_seed():
        try:
            from seed_demo_library import auto_seed_if_needed
            auto_seed_if_needed()
        except Exception:
            pass
    threading.Thread(target=_auto_seed, daemon=True).start()
    yield
    # shutdown: stop the managed intake scheduler (no-op if it was never started)
    try:
        scheduler_manager.stop()
    except Exception:
        logging.getLogger(__name__).exception("intake scheduler shutdown failed")


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
    version=APP_VERSION,
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
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Request-ID",
        "X-BOH-Operator-Token",
        "X-BOH-Actor-ID",
        "X-BOH-Retrieval-Token",
    ],
)


# ── Targeted error mapping ────────────────────────────────────────────────────
# A numeric query/path parameter too large for SQLite (e.g. ?limit > 2^63-1) raises
# OverflowError when bound into a query, which would otherwise surface as a bare 500.
# That is client input, not a server fault → return 422. Narrowly scoped to OverflowError
# so genuine server-side errors still surface as 500.
from fastapi import Request as _Request                      # noqa: E402
from fastapi.responses import JSONResponse as _JSONResponse  # noqa: E402


@app.exception_handler(OverflowError)
async def _overflow_to_422(_request: _Request, _exc: OverflowError):
    return _JSONResponse(
        status_code=422,
        content={"detail": "Numeric parameter out of range."},
    )


# ── API routers — registered BEFORE static mount ──────────────────────────────
for router in (
    index.router,
    search.router,
    canon.router,
    conflicts.router,
    library.router,
    libraries.router,
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
    actor_router,                # Phase 28: Actor authority ledger
    retrieval_router,            # Retrieval v1: read-only LLM context packs
    intake_router,               # Phase 7: Intake layer API
    fold_router,                 # Current Fold View: /api/fold/node/{doc_id}
    trace_router,                # Phase 7: Trace Ledger surface (read-only gate results)
    review_queue_router,         # Phase 7: Review Queue surface (patch proposal adjudication)
    residence_router,            # Phase 7: Residence Map surface (read-only information residence)
    context_pack_router,         # Phase 7: Context Pack Builder surface (read-only assembler)
    context_object_router,       # WO-R2: /api/context-object (Levels 5+3, retrieval-token gated)
    current_context_brief_router,  # CurrentContextBrief v0.1: retrieval-token gated context search
    security_settings_router,      # Local persistent token configuration
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
        "version": APP_VERSION,
        "phase":   SYSTEM_PHASE,
        "status_label": STATUS_LABEL,
        "db":      db_status,
        "library": library_root,
    }


@app.get("/api/operator/status", summary="Operator authorization status", tags=["system"])
def get_operator_status():
    return operator_status()


@app.post("/api/operator/check", summary="Validate operator authorization without mutation", tags=["system"])
def check_operator(_operator: str = Depends(require_operator)):
    return {"ok": True}


@app.post("/api/operator/diagnostic", summary="Validate protected UI headers without mutation", tags=["system"])
def operator_diagnostic(
    _operator: str = Depends(require_operator),
    x_boh_actor_id: str | None = Header(default=None, alias="X-BOH-Actor-ID"),
):
    return {
        "ok": True,
        "operator_header_received": True,
        "actor_header_received": bool(x_boh_actor_id),
        "actor_id": x_boh_actor_id or "local_operator",
        "token_value_revealed": False,
    }


@app.get("/api/workspace/boundary-check", summary="Filesystem boundary self-check", tags=["system"])
def boundary_check():
    try:
        resolve_under_library("../outside.txt")
        return {"escape_rejected": False}
    except PathBoundaryViolation:
        return {"escape_rejected": True}


# ── SPA static files — mounted LAST so /api/* routes take priority ────────────
_ui_dir = Path(__file__).parent.parent / "ui"
_ui2_dir = Path(__file__).parent.parent / "ui2"
_vendor_dir = _ui_dir / "vendor"


class _CachelessStaticFiles(StaticFiles):
    """StaticFiles that tells the browser to always revalidate UI assets.

    The /v2 UI is a build-free ES-module graph: a single stale cached module can run
    against fresh siblings and produce hard-to-diagnose breakage (e.g. an old fold.js).
    `no-cache` forces revalidation against the server's ETag/Last-Modified on every load,
    so the browser fetches changed modules immediately while unchanged ones still 304.
    Vendor libraries are served by plain StaticFiles and may cache normally.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


if _vendor_dir.exists():
    # Vendor libraries (KaTeX, marked.js) — absolute /vendor/ paths work from any UI path.
    app.mount("/vendor", StaticFiles(directory=str(_vendor_dir)), name="vendor")

if _ui2_dir.exists():
    # /v2 preserved for backward compatibility (existing bookmarks and linked docs).
    app.mount("/v2", _CachelessStaticFiles(directory=str(_ui2_dir), html=True), name="ui2_compat")

if _ui_dir.exists():
    # Classic UI at /classic — operator-token mutations remain accessible here until
    # action-button wiring in the new UI is complete (boh_ui_cutover_v0_1).
    app.mount("/classic", _CachelessStaticFiles(directory=str(_ui_dir), html=True), name="ui_classic")

if _ui2_dir.exists():
    # New governed UI is the default at /. Must be last — greedy SPA catch-all.
    app.mount("/", _CachelessStaticFiles(directory=str(_ui2_dir), html=True), name="ui")

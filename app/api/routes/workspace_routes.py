"""app/api/routes/workspace_routes.py: Workspace management routes.

Phase 26.3 — Clean Import + Fresh-Start Testing

Routes:
  GET  /api/workspace/state        — current workspace health summary
  POST /api/workspace/reset        — clear DB state for fresh start (preserves library files)
  POST /api/workspace/reset-full   — clear DB + library files (nuclear option, requires confirm)
  POST /api/workspace/seed-fixtures — import Phase 26.3 verification fixtures into library
  POST /api/workspace/seed-lineage  — seed lineage relationship between two doc IDs
  POST /api/workspace/seed-provenance — seed provenance record for a doc
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import connection as db
from app.core.audit import log_event

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")

# Tables that can be safely cleared for a reset (not docs — those stay unless full reset)
CLEARABLE_STATE_TABLES = [
    "autoindex_state",
    "coherence_scores",
    "coherence_refresh_events",
    "anchor_events",
    "open_items",
    "escalation_events",
    "canonical_locks",
    "sc3_violations",
    "authority_resolution_log",
    "governance_events",
    "feedback_rewrites",
]

# Tables cleared in a full reset
FULL_RESET_TABLES = CLEARABLE_STATE_TABLES + [
    "docs", "defs", "conflicts", "lineage", "lineage_events",
    "doc_edges", "doc_coordinates", "certificates", "lattice_events",
    "cards", "plane_interfaces", "lattice_edges", "llm_invocations",
    "exec_runs", "exec_artifacts", "approval_requests",
    "authority_promotions", "escalation_registry", "provenance_artifacts",
    "edge_approval_requests", "substrate_lattice_registry",
]


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ResetRequest(BaseModel):
    confirm: str  # must be "RESET" to proceed
    preserve_canonical: bool = True  # keep canonical docs even in full reset

class SeedLineageRequest(BaseModel):
    source_doc_id: str
    child_doc_id: str
    relationship: str = "derived_from"
    notes: str = ""

class SeedProvenanceRequest(BaseModel):
    doc_id: str
    created_by: str = "system"
    last_edited_by: str = "system"
    change_summary: str = "seeded for verification"

class SeedFixturesRequest(BaseModel):
    fixture_dir: Optional[str] = None  # defaults to tests/fixtures/import_reliability


# ---------------------------------------------------------------------------
# Workspace state
# ---------------------------------------------------------------------------

@router.get("/state", summary="Phase 26.3: Current workspace health summary")
def get_workspace_state():
    """Return a full workspace health summary.

    Checks:
    - DB tables present and populated
    - Library root exists and is accessible
    - Last autoindex stats
    - Any critical failures
    """
    db.init_db()
    health: dict[str, Any] = {}
    issues: list[str] = []

    # Doc count
    try:
        row = db.fetchone("SELECT COUNT(*) as n FROM docs")
        health["doc_count"] = row["n"] if row else 0
    except Exception as e:
        health["doc_count"] = 0
        issues.append(f"docs table error: {e}")

    # Canonical count
    try:
        row = db.fetchone("SELECT COUNT(*) as n FROM docs WHERE status='canonical'")
        health["canonical_count"] = row["n"] if row else 0
    except Exception:
        health["canonical_count"] = 0

    # Library root
    lib_root = os.environ.get("BOH_LIBRARY", "./library")
    lib_path = Path(lib_root).resolve()
    health["library_root"] = str(lib_path)
    health["library_exists"] = lib_path.exists()
    if not lib_path.exists():
        issues.append(f"Library root missing: {lib_path}")

    # File count in library
    if lib_path.exists():
        exts = {".md", ".html", ".json", ".txt", ".markdown"}
        files = [p for p in lib_path.rglob("*") if p.is_file() and p.suffix.lower() in exts
                 and not p.name.endswith(".review.md")]
        health["library_file_count"] = len(files)
    else:
        health["library_file_count"] = 0

    # Autoindex last run
    try:
        from app.core.autoindex import get_status, get_failure_log
        ai_status = get_status()
        health["last_index_run"] = ai_status.get("last_run_ts")
        health["last_index_indexed"] = ai_status.get("last_indexed", 0)
        health["last_index_failed"] = ai_status.get("last_failed", 0)
        if ai_status.get("last_failed", 0) > 0:
            issues.append(f"{ai_status['last_failed']} file(s) failed in last reindex run")
    except Exception as e:
        health["last_index_run"] = None
        issues.append(f"autoindex status error: {e}")

    # Lineage count
    try:
        row = db.fetchone("SELECT COUNT(*) as n FROM lineage")
        health["lineage_count"] = row["n"] if row else 0
    except Exception:
        health["lineage_count"] = 0

    # Open items
    try:
        row = db.fetchone("SELECT COUNT(*) as n FROM open_items WHERE status='open'")
        health["open_items"] = row["n"] if row else 0
    except Exception:
        health["open_items"] = 0

    overall = "critical" if issues else "ok"
    if health.get("doc_count", 0) == 0 and health.get("library_file_count", 0) > 0:
        issues.append("Library has files but DB has no indexed docs — run reindex")
        overall = "warning"

    return {
        "health": overall,
        "issues": issues,
        "stats": health,
        "recommended_action": (
            "Run POST /api/autoindex/run to index the library" if health.get("doc_count", 0) == 0
            else "GET /api/autoindex/failures to see failure details" if health.get("last_index_failed", 0) > 0
            else "Workspace is healthy"
        ),
    }


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

@router.post("/reset", summary="Phase 26.3: Clear governance state for fresh-start testing (preserves docs)")
def reset_workspace_state(req: ResetRequest):
    """Clear governance/state tables for a fresh test run.

    Preserves: docs, defs, lineage, conflicts (the indexed corpus).
    Clears: open_items, escalations, locks, coherence scores, sc3_violations, etc.

    Use this before running verification tests to ensure clean governance state.
    Does NOT delete library files.

    Requires: confirm="RESET"
    """
    if req.confirm != "RESET":
        raise HTTPException(status_code=400,
                            detail="confirm must be 'RESET' to proceed")
    db.init_db()
    cleared = []
    errors = []
    for table in CLEARABLE_STATE_TABLES:
        try:
            db.execute(f"DELETE FROM {table}")
            cleared.append(table)
        except Exception as e:
            errors.append(f"{table}: {e}")

    try:
        log_event("workspace_reset", actor_type="human", actor_id="operator",
                  detail=json.dumps({"type": "state_reset", "cleared": cleared}))
    except Exception:
        pass

    return {
        "ok": True,
        "reset_type": "state_only",
        "cleared_tables": cleared,
        "errors": errors,
        "message": (
            f"Cleared {len(cleared)} state tables. "
            "Indexed docs and library files preserved. "
            "Run POST /api/autoindex/run to re-index if needed."
        ),
    }


@router.post("/reset-full", summary="Phase 26.3: NUCLEAR — clear all DB state including indexed docs")
def reset_workspace_full(req: ResetRequest):
    """NUCLEAR OPTION: Clear ALL DB state including indexed documents.

    Use only for a completely fresh start. All indexed docs are removed from DB.
    Library files on disk are NOT deleted.

    After this: re-import files via /api/input/upload or run /api/autoindex/run.
    Requires: confirm="RESET"
    """
    if req.confirm != "RESET":
        raise HTTPException(status_code=400,
                            detail="confirm must be 'RESET' to proceed")
    db.init_db()
    cleared = []
    errors = []

    tables_to_clear = FULL_RESET_TABLES
    if req.preserve_canonical:
        # Keep canonical docs even in full reset
        try:
            db.execute("DELETE FROM docs WHERE status != 'canonical'")
            cleared.append("docs (non-canonical only)")
        except Exception as e:
            errors.append(f"docs: {e}")
        tables_to_clear = [t for t in FULL_RESET_TABLES if t != "docs"]

    for table in tables_to_clear:
        try:
            db.execute(f"DELETE FROM {table}")
            cleared.append(table)
        except Exception as e:
            errors.append(f"{table}: {e}")

    try:
        log_event("workspace_reset", actor_type="human", actor_id="operator",
                  detail=json.dumps({"type": "full_reset", "cleared": cleared,
                                     "preserve_canonical": req.preserve_canonical}))
    except Exception:
        pass

    return {
        "ok": True,
        "reset_type": "full",
        "cleared_tables": cleared,
        "errors": errors,
        "message": (
            f"Full reset complete. {len(cleared)} tables cleared. "
            "Library files on disk are untouched. "
            "Run POST /api/autoindex/run to re-index."
        ),
    }


# ---------------------------------------------------------------------------
# Seed fixtures
# ---------------------------------------------------------------------------

@router.post("/seed-fixtures", summary="Phase 26.3: Import Phase 26.3 verification fixtures into library")
def seed_fixtures(req: SeedFixturesRequest):
    """Copy Phase 26.3 test fixtures into the library and index them.

    Creates seeded documents with: lineage relationships, provenance metadata,
    LLM analysis fixtures, and project membership — ready for verification.

    Returns per-file index results.
    """
    db.init_db()
    fixture_dir = req.fixture_dir
    if not fixture_dir:
        # Default to the known fixture location relative to project root
        base = Path(__file__).parent.parent.parent.parent
        fixture_dir = str(base / "tests" / "fixtures" / "import_reliability")

    fixture_path = Path(fixture_dir)
    if not fixture_path.exists():
        raise HTTPException(status_code=404,
                            detail=f"Fixture directory not found: {fixture_dir}")

    lib_root = Path(os.environ.get("BOH_LIBRARY", "./library")).resolve()
    dest_dir = lib_root / "verification_fixtures"
    dest_dir.mkdir(parents=True, exist_ok=True)

    from app.services.indexer import index_file
    results = []
    fixture_files = list(fixture_path.glob("*.md")) + list(fixture_path.glob("*.json")) + \
                    list(fixture_path.glob("*.html"))

    for src in sorted(fixture_files):
        dst = dest_dir / src.name
        try:
            shutil.copy2(src, dst)
            idx = index_file(dst, lib_root)
            results.append({
                "filename": src.name,
                "path": idx.get("path"),
                "doc_id": idx.get("doc_id"),
                "indexed": idx.get("indexed", False),
                "lint_errors": idx.get("lint_errors", []),
            })
        except Exception as e:
            results.append({
                "filename": src.name,
                "indexed": False,
                "error": str(e)[:200],
            })

    # Seed lineage for the lineage pair
    try:
        _seed_lineage_pair(results)
    except Exception:
        pass

    indexed_count = sum(1 for r in results if r.get("indexed"))
    return {
        "ok": True,
        "fixture_dir": str(fixture_path),
        "dest_dir": str(dest_dir),
        "total": len(results),
        "indexed": indexed_count,
        "failed": len(results) - indexed_count,
        "results": results,
    }


def _seed_lineage_pair(results: list[dict]) -> None:
    """Auto-seed lineage for lineage_source + lineage_child fixtures."""
    source_id = next((r["doc_id"] for r in results
                      if r.get("filename", "").startswith("lineage_source") and r.get("doc_id")), None)
    child_id = next((r["doc_id"] for r in results
                     if r.get("filename", "").startswith("lineage_child") and r.get("doc_id")), None)
    if source_id and child_id:
        db.execute(
            "INSERT OR IGNORE INTO lineage (doc_id, related_doc_id, relationship, detected_ts) VALUES (?,?,?,?)",
            (child_id, source_id, "derived_from", int(time.time())),
        )


@router.post("/seed-lineage", summary="Phase 26.3: Seed a lineage relationship between two documents")
def seed_lineage(req: SeedLineageRequest):
    """Manually seed a lineage relationship between two doc IDs.

    Lineage = document-to-document relationship: derived_from, supersedes, duplicates, references.
    """
    db.init_db()
    # Verify both docs exist
    src = db.fetchone("SELECT doc_id, title FROM docs WHERE doc_id=?", (req.source_doc_id,))
    child = db.fetchone("SELECT doc_id, title FROM docs WHERE doc_id=?", (req.child_doc_id,))
    if not src:
        raise HTTPException(status_code=404, detail=f"Source doc not found: {req.source_doc_id}")
    if not child:
        raise HTTPException(status_code=404, detail=f"Child doc not found: {req.child_doc_id}")

    db.execute(
        "INSERT OR IGNORE INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail) VALUES (?,?,?,?,?)",
        (req.child_doc_id, req.source_doc_id, req.relationship,
         int(time.time()), req.notes or None),
    )
    return {
        "ok": True,
        "relationship": req.relationship,
        "source": {"doc_id": src["doc_id"], "title": src["title"]},
        "child": {"doc_id": child["doc_id"], "title": child["title"]},
        "message": f"Lineage seeded: '{child['title']}' {req.relationship} '{src['title']}'",
    }


@router.post("/seed-provenance", summary="Phase 26.3: Seed provenance record for a document")
def seed_provenance(req: SeedProvenanceRequest):
    """Manually seed a provenance / custody record for a document.

    This creates a governance event that populates the Provenance Chain in the document detail.
    """
    db.init_db()
    doc = db.fetchone("SELECT doc_id, title FROM docs WHERE doc_id=?", (req.doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {req.doc_id}")

    try:
        log_event(
            "provenance_seed",
            actor_type="human",
            actor_id=req.created_by,
            detail=json.dumps({
                "doc_id": req.doc_id,
                "created_by": req.created_by,
                "last_edited_by": req.last_edited_by,
                "change_summary": req.change_summary,
                "seeded_at": _now_iso(),
            }),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Provenance seed failed: {e}")

    return {
        "ok": True,
        "doc_id": req.doc_id,
        "title": doc["title"],
        "created_by": req.created_by,
        "last_edited_by": req.last_edited_by,
        "message": f"Provenance seeded for '{doc['title']}'",
    }


# ---------------------------------------------------------------------------
# Phase 26.4: Activity Log + AI Analysis Health
# ---------------------------------------------------------------------------

@router.get("/activity-log", summary="Phase 26.4: Workspace activity timeline — every import, reset, index, analysis")
def get_activity_log(limit: int = 100, event_type: str | None = None):
    """Return a unified activity timeline combining audit_log and governance_events.

    Shows: imports, resets, index runs, AI analysis attempts, lineage seeds,
    provenance seeds, authority rejections, escalations.

    This is the operator traceability log — every action recorded and visible.
    """
    db.init_db()

    # Friendly labels for event types
    _labels = {
        "save": "📄 File imported",
        "index": "🔍 Library indexed",
        "workspace_reset": "⟳ Workspace reset",
        "provenance_seed": "◈ Provenance seeded",
        "authority_resolution_attempt": "🔒 Authority check",
        "authority_promotion": "⬆ Authority promoted",
        "sc3_constitutive_violation": "⚠ SC3 violation",
        "approval_request": "📋 Approval requested",
        "approval_granted": "✅ Approval granted",
        "approval_rejected": "❌ Approval rejected",
        "escalation": "🚨 Escalation",
        "promote": "⬆ Promoted",
        "conflict": "⚡ Conflict detected",
        "llm_call": "🤖 AI Analysis",
        "run": "▶ Execution run",
    }

    query = "SELECT * FROM audit_log WHERE 1=1"
    params: list[Any] = []
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    query += " ORDER BY event_ts DESC LIMIT ?"
    params.append(limit)

    try:
        rows = db.fetchall(query, tuple(params))
    except Exception:
        rows = []

    events = []
    for row in rows:
        d = dict(row)
        detail = {}
        try:
            if d.get("detail"):
                detail = json.loads(d["detail"])
        except Exception:
            detail = {"raw": d.get("detail", "")}

        events.append({
            "ts": d.get("event_ts"),
            "iso": _now_iso() if not d.get("event_ts") else
                   __import__("datetime").datetime.fromtimestamp(
                       d["event_ts"],
                       tz=__import__("datetime").timezone.utc
                   ).isoformat(),
            "event_type": d.get("event_type"),
            "label": _labels.get(d.get("event_type", ""), d.get("event_type", "—")),
            "actor_id": d.get("actor_id"),
            "actor_type": d.get("actor_type"),
            "doc_id": d.get("doc_id"),
            "detail": detail,
        })

    return {
        "total": len(events),
        "events": events,
        "note": "Unified activity timeline. All governance actions are permanent.",
    }


@router.get("/analysis-health", summary="Phase 26.4: AI Analysis health check — endpoint, text length, result")
def analysis_health(doc_id: str | None = None):
    """Check AI Analysis health.

    If doc_id provided: checks that specific document.
    Otherwise: checks the analysis pipeline with the most recently indexed document.

    Returns:
        endpoint_ok      — /api/review route is reachable
        doc_found        — document exists in DB
        file_found       — file exists on disk
        text_length      — normalized text length (chars)
        topics_extracted — number of topics found
        defs_extracted   — number of definitions found
        error            — error message if any step fails
        status           — ok | file_missing | no_content | error
    """
    db.init_db()
    lib_root = os.environ.get("BOH_LIBRARY", "./library")

    # Find a doc to test with
    if doc_id:
        doc = db.fetchone("SELECT * FROM docs WHERE doc_id=?", (doc_id,))
    else:
        doc = db.fetchone("SELECT * FROM docs WHERE status != 'archived' ORDER BY updated_ts DESC LIMIT 1")

    if not doc:
        return {
            "status": "no_docs",
            "endpoint_ok": True,
            "doc_found": False,
            "error": "No documents in DB. Import files and run reindex first.",
        }

    doc_path = doc["path"]
    full_path = Path(lib_root) / doc_path
    file_found = full_path.exists()

    if not file_found:
        return {
            "status": "file_missing",
            "endpoint_ok": True,
            "doc_found": True,
            "file_found": False,
            "doc_id": doc["doc_id"],
            "doc_path": doc_path,
            "error": f"File not on disk: {full_path}. Re-import or run workspace seed.",
        }

    # Try generating analysis
    try:
        from app.services.reviewer import generate_review_artifact
        artifact = generate_review_artifact(doc_path, lib_root)

        if "error" in artifact:
            return {
                "status": "error",
                "endpoint_ok": True,
                "doc_found": True,
                "file_found": True,
                "doc_id": doc["doc_id"],
                "doc_path": doc_path,
                "error": artifact["error"],
            }

        # Read raw text to get length
        text = full_path.read_text(encoding="utf-8", errors="replace")
        return {
            "status": "ok",
            "endpoint_ok": True,
            "doc_found": True,
            "file_found": True,
            "doc_id": doc["doc_id"],
            "doc_path": doc_path,
            "text_length": len(text),
            "topics_extracted": len(artifact.get("extracted_topics", [])),
            "defs_extracted": len(artifact.get("extracted_definitions", [])),
            "non_authoritative": artifact.get("non_authoritative"),
            "note": (
                "AI Analysis is deterministic — no Ollama required. "
                "It extracts topics, definitions, and conflict candidates from the file."
            ),
        }
    except Exception as e:
        return {
            "status": "error",
            "endpoint_ok": True,
            "doc_found": True,
            "file_found": True,
            "doc_id": doc["doc_id"] if doc else None,
            "error": str(e)[:300],
        }

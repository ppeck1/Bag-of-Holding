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

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from app.db import connection as db
from app.core.auth import require_operator
from app.core import actor_ledger as al
from app.core.audit import log_event
from app.core.fs_boundary import (
    PathBoundaryViolation,
    assert_write_safe,
    get_library_root,
    resolve_under_library,
    safe_write_text,
)

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

APP_OWNED_RESET_DIRS = {
    "verification_fixtures",
    "fixtures/primitive_test",
    "demo-phase-16-1",
    "scratch",
    "imports",
}
QUARANTINE_DIR = ".boh_quarantine"
PRIMITIVE_SEED_NAMESPACE = "primitive_test"
PRIMITIVE_SEED_ROOT = "fixtures/primitive_test"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _table_exists(table: str) -> bool:
    row = db.fetchone(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (table,),
    )
    return bool(row)


def _clear_table(table: str) -> tuple[bool, int | str]:
    if not _table_exists(table):
        return False, "missing"
    try:
        before = db.fetchone(f"SELECT COUNT(*) as n FROM {table}")
        db.execute(f"DELETE FROM {table}")
        return True, int(before["n"] if before else 0)
    except Exception as exc:
        return False, str(exc)


def _clear_fts() -> tuple[bool, int | str]:
    if not _table_exists("docs_fts"):
        return False, "missing"
    try:
        before = db.fetchone("SELECT COUNT(*) as n FROM docs_fts")
        db.execute("DELETE FROM docs_fts")
        return True, int(before["n"] if before else 0)
    except Exception as exc:
        return False, str(exc)


def _is_app_owned_path(rel: str) -> bool:
    normalized = rel.replace("\\", "/").strip("/")
    return (
        normalized.endswith(".review.json")
        or normalized.endswith(".review.md")
        or any(normalized == d or normalized.startswith(d + "/") for d in APP_OWNED_RESET_DIRS)
    )


def _library_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    quarantine_prefix = f"{QUARANTINE_DIR}/"
    files = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == QUARANTINE_DIR or rel.startswith(quarantine_prefix):
            continue
        files.append(p)
    return files


def _safe_remove_file(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    target = resolve_under_library(rel, root)
    target.unlink(missing_ok=True)
    return rel


def _safe_quarantine_file(path: Path, root: Path, stamp: str) -> str:
    rel = path.relative_to(root).as_posix()
    src = resolve_under_library(rel, root)
    dest_rel = f"{QUARANTINE_DIR}/{stamp}/{rel}"
    dest = resolve_under_library(dest_rel, root)
    assert_write_safe(dest, root, entity_type="operator", entity_id="workspace_reset")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest_rel


def _prune_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p == root or not p.is_dir() or p.name == QUARANTINE_DIR:
            continue
        try:
            p.rmdir()
        except OSError:
            pass


def _remove_stale_doc_refs(root: Path) -> list[dict]:
    removed: list[dict] = []
    if not _table_exists("docs"):
        return removed
    rows = db.fetchall("SELECT doc_id, path, corpus_class FROM docs")
    from app.core import promoted_exposure
    for row in rows:
        doc_id = row["doc_id"]
        path = row["path"] or ""
        # WO-2 mutation isolation: a promoted doc row is ledger-governed — even if its managed
        # file is missing, deletion goes through governed demote(), never workspace cleanup.
        if promoted_exposure.is_promoted_row(row):
            continue
        missing = False
        try:
            resolved = resolve_under_library(path, root)
            missing = not resolved.exists()
        except Exception:
            missing = True
        if missing:
            db.execute("DELETE FROM docs WHERE doc_id = ?", (doc_id,))
            if _table_exists("docs_fts"):
                db.execute("DELETE FROM docs_fts WHERE path = ?", (path,))
            if _table_exists("defs"):
                db.execute("DELETE FROM defs WHERE doc_id = ?", (doc_id,))
            removed.append({"doc_id": doc_id, "path": path})
    return removed


def _workspace_inventory(root: Path) -> dict[str, Any]:
    from app.core import autoindex

    supported = {".md", ".txt", ".markdown", ".html", ".htm", ".json"}
    files = []
    by_folder: dict[str, int] = {}
    if root.exists():
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in supported:
                continue
            rel = p.relative_to(root).as_posix()
            files.append(rel)
            top = rel.split("/")[0] if "/" in rel else "."
            by_folder[top] = by_folder.get(top, 0) + 1

    manifest = autoindex.discover_manifest(str(root), max_files=20000)
    return {
        "files_remaining_total": len(files),
        "files_remaining_by_folder": by_folder,
        "quarantine_files_total": sum(1 for r in files if r.startswith(".boh_quarantine/")),
        "primitive_fixture_files_total": sum(1 for r in files if r.startswith("fixtures/primitive_test/")
                                             and autoindex.classify_relative_path(r) != "review_artifact"),
        "indexed_candidates_total": sum(1 for m in manifest if m["action"] == "candidate"),
        "review_artifact_files_total": sum(1 for r in files if autoindex.classify_relative_path(r) == "review_artifact"),
        "manifest": manifest,
    }


def _primitive_seed_files() -> dict[str, str]:
    now = "2026-05-19T00:00:00+00:00"

    def fm(doc_id: str, title: str, doc_type: str = "note", status: str = "draft",
           operator_state: str = "observe", operator_intent: str = "capture",
           topics: list[str] | None = None) -> str:
        topic_lines = "\n".join(f"    - {t}" for t in (topics or ["primitive-test"]))
        return f"""---
boh:
  id: "{doc_id}"
  document_id: "{doc_id}"
  title: "{title}"
  type: "{doc_type}"
  document_class: "{doc_type}"
  status: "{status}"
  canonical_layer: "supporting"
  authority_state: "draft"
  review_state: "none"
  project: "Primitive Test"
  version: "1.0.0"
  updated: "{now}"
  source_hash: "seed-{doc_id}"
  provenance:
    mode: "primitive_seed"
    source: "workspace.seed-fixtures"
  topics:
{topic_lines}
  scope:
    plane_scope: ["primitive"]
    field_scope: ["seed"]
    node_scope: ["{doc_id}"]
  rubrix:
    operator_state: "{operator_state}"
    operator_intent: "{operator_intent}"
    next_operator: null
---

"""

    return {
        "valid_markdown.md": fm("primitive-valid-md", "Primitive Valid Markdown", topics=["primitive-test", "markdown"]) +
        "# Primitive Valid Markdown\n\nThis fixture is a stable Markdown document for boundary and reader checks.\n",
        "sample.html": """<!doctype html>
<html><head><title>Primitive HTML Fixture</title></head>
<body>
  <h1>Primitive HTML Fixture</h1>
  <p>This HTML file includes a <a href="https://example.test/reference">reference link</a>.</p>
  <table><tr><th>Name</th><th>Value</th></tr><tr><td>alpha</td><td>1</td></tr></table>
</body></html>
""",
        "nested/path-preserved.md": fm("primitive-nested-md", "Nested Path Preserved", topics=["primitive-test", "nested"]) +
        "# Nested Path Preserved\n\nThis nested fixture proves relative browser paths survive intake and indexing.\n",
        "duplicates/duplicate-a.md": fm("primitive-duplicate-a", "Duplicate A", topics=["primitive-test", "duplicate"]) +
        "# Duplicate Pair\n\nThe duplicated body text is intentionally the same for duplicate detection.\n",
        "duplicates/duplicate-b.md": fm("primitive-duplicate-b", "Duplicate B", topics=["primitive-test", "duplicate"]) +
        "# Duplicate Pair\n\nThe duplicated body text is intentionally the same for duplicate detection.\n",
        "lineage/source.md": fm("primitive-lineage-source", "Lineage Source", topics=["primitive-test", "lineage"]) +
        "# Lineage Source\n\nThis document is the source for a deterministic derived fixture.\n",
        "lineage/child.md": fm("primitive-lineage-child", "Lineage Child", topics=["primitive-test", "lineage"]) +
        "# Lineage Child\n\nThis document derives from the deterministic source fixture.\n",
        "lifecycle/rubrix-sample.md": fm(
            "primitive-rubrix-sample",
            "Rubrix Lifecycle Sample",
            operator_state="vessel",
            operator_intent="organize",
            topics=["primitive-test", "rubrix"],
        ) + "# Rubrix Lifecycle Sample\n\nobserve -> vessel -> constraint -> integrate -> release.\n",
        "review/review-target.md": fm("primitive-review-target", "Review Artifact Target", topics=["primitive-test", "review"]) +
        "# Review Artifact Target\n\nThis fixture gives the reviewer a safe target under the library boundary.\n",
    }


def _seed_primitive_fixtures(reindex: bool = True) -> dict:
    root = get_library_root()
    root.mkdir(parents=True, exist_ok=True)
    files_created: list[str] = []
    files_skipped: list[str] = []
    files_replaced: list[str] = []
    warnings: list[str] = []
    results: list[dict] = []
    seed_files = _primitive_seed_files()

    for rel_tail, content in seed_files.items():
        rel = f"{PRIMITIVE_SEED_ROOT}/{rel_tail}"
        target = resolve_under_library(rel, root)
        existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else None
        if existing == content:
            files_skipped.append(rel)
        else:
            safe_write_text(
                target,
                content,
                root,
                entity_type="operator",
                entity_id="primitive_seed",
            )
            if existing is None:
                files_created.append(rel)
            else:
                files_replaced.append(rel)

    indexed = False
    db_rows_created: dict[str, int] = {}
    if reindex:
        from app.services.indexer import index_file
        for rel_tail in seed_files:
            rel = f"{PRIMITIVE_SEED_ROOT}/{rel_tail}"
            target = resolve_under_library(rel, root)
            try:
                idx = index_file(target, root)
                results.append(idx)
            except Exception as exc:
                warnings.append(f"{rel}: {exc}")
        indexed = any(r.get("indexed") for r in results)
        db_rows_created["docs"] = sum(1 for r in results if r.get("indexed"))

        try:
            db.execute(
                "INSERT OR IGNORE INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail) VALUES (?,?,?,?,?)",
                ("primitive-lineage-child", "primitive-lineage-source", "derived_from", int(time.time()), "primitive seed"),
            )
            db_rows_created["lineage"] = 1
        except Exception as exc:
            warnings.append(f"lineage seed failed: {exc}")

    return {
        "ok": not warnings,
        "seed_namespace": PRIMITIVE_SEED_NAMESPACE,
        "files_created": files_created,
        "files_skipped": files_skipped,
        "files_replaced": files_replaced,
        "db_rows_created": db_rows_created,
        "indexed": indexed,
        "warnings": warnings,
        "results": results,
    }


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
    inventory = _workspace_inventory(lib_path)
    health["library_file_count"] = inventory["files_remaining_total"]
    health["indexed_candidates_total"] = inventory["indexed_candidates_total"]
    health["primitive_fixture_files_total"] = inventory["primitive_fixture_files_total"]
    health["review_artifact_files_total"] = inventory["review_artifact_files_total"]
    health["quarantine_files_total"] = inventory["quarantine_files_total"]

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
def reset_workspace_state(req: ResetRequest, _operator: str = Depends(require_operator)):
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
        al.ledger_event("reset_workspace", "workspace", "state", actor_id="local_operator",
                        authority_result="allowed", authority_basis="grant:bootstrap-or-operator",
                        after={"cleared_tables": cleared, "errors": errors},
                        source_route="/api/workspace/reset")
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
def reset_workspace_full(req: ResetRequest, _operator: str = Depends(require_operator),
                         x_boh_actor_id: Optional[str] = Header(default=None, alias="X-BOH-Actor-ID")):
    """Recover to a clean test workspace without escaping BOH_LIBRARY."""
    if req.confirm != "RESET":
        raise HTTPException(status_code=400,
                            detail="confirm must be 'RESET' to proceed")
    actor_id = al.actor_from_env_or_header(x_boh_actor_id)
    allowed, basis = al.evaluate_authority(actor_id, "reset_workspace", "workspace", str(get_library_root()), operator_authorized=True)
    if not allowed:
        al.ledger_event("reset_workspace", "workspace", "full", actor_id=actor_id,
                        authority_result="denied", authority_basis=basis,
                        source_route="/api/workspace/reset-full")
        raise HTTPException(status_code=403, detail=f"actor lacks authority: {basis}")
    db.init_db()
    root = get_library_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())

    report: dict[str, Any] = {
        "ok": True,
        "files_removed": [],
        "files_quarantined": [],
        "artifacts_removed": [],
        "stale_refs_removed": [],
        "db_rows_removed": {},
        "fixtures_seeded": False,
        "reindex_status": "skipped",
        "warnings": [],
    }

    try:
        report["stale_refs_removed"] = _remove_stale_doc_refs(root)
    except Exception as exc:
        report["warnings"].append(f"stale ref cleanup failed: {exc}")

    for p in _library_files(root):
        try:
            rel = p.relative_to(root).as_posix()
            if _is_app_owned_path(rel):
                removed = _safe_remove_file(p, root)
                if removed.endswith(".review.json") or removed.endswith(".review.md"):
                    report["artifacts_removed"].append(removed)
                else:
                    report["files_removed"].append(removed)
            else:
                report["files_quarantined"].append(_safe_quarantine_file(p, root, stamp))
        except Exception as exc:
            report["warnings"].append(f"{p}: {exc}")

    try:
        _prune_empty_dirs(root)
    except Exception as exc:
        report["warnings"].append(f"empty directory cleanup failed: {exc}")

    for table in FULL_RESET_TABLES:
        ok, value = _clear_table(table)
        if ok:
            report["db_rows_removed"][table] = value
        elif value != "missing":
            report["warnings"].append(f"{table}: {value}")

    ok, value = _clear_fts()
    if ok:
        report["db_rows_removed"]["docs_fts"] = value
    elif value != "missing":
        report["warnings"].append(f"docs_fts: {value}")

    report.update(_workspace_inventory(root))

    try:
        log_event("workspace_reset", actor_type="human", actor_id="operator",
                  detail=json.dumps({"type": "full_clean_reset", **report}))
        al.ledger_event("reset_workspace", "workspace", "full", actor_id=actor_id,
                        authority_result="allowed", authority_basis=basis,
                        after=report, source_route="/api/workspace/reset-full")
    except Exception:
        pass

    report["ok"] = True
    return report


# ---------------------------------------------------------------------------
# Seed fixtures
# ---------------------------------------------------------------------------

@router.post("/seed-fixtures", summary="Phase 26.3: Import Phase 26.3 verification fixtures into library")
def seed_fixtures(req: SeedFixturesRequest, _operator: str = Depends(require_operator),
                  x_boh_actor_id: Optional[str] = Header(default=None, alias="X-BOH-Actor-ID")):
    """Copy Phase 26.3 test fixtures into the library and index them.

    Creates seeded documents with: lineage relationships, provenance metadata,
    LLM analysis fixtures, and project membership — ready for verification.

    Returns per-file index results.
    """
    db.init_db()
    if req.fixture_dir:
        raise HTTPException(
            status_code=403,
            detail="caller-supplied fixture_dir is disabled; primitive fixtures are server-owned",
        )
    result = _seed_primitive_fixtures(reindex=True)
    result["total"] = (
        len(result["files_created"])
        + len(result["files_skipped"])
        + len(result["files_replaced"])
    )
    result["indexed_count"] = sum(1 for r in result.get("results", []) if r.get("indexed"))
    result["failed"] = len(result["warnings"])
    inventory = _workspace_inventory(get_library_root())
    result.update({
        "expected_source_fixture_count": len(_primitive_seed_files()),
        "actual_source_fixture_count": inventory["primitive_fixture_files_total"],
        "review_artifact_count": inventory["review_artifact_files_total"],
        "indexed_candidate_count": inventory["indexed_candidates_total"],
    })
    try:
        actor_id = al.actor_from_env_or_header(x_boh_actor_id)
        al.ledger_event("seed_fixtures", "workspace", PRIMITIVE_SEED_NAMESPACE, actor_id=actor_id,
                        authority_result="allowed", authority_basis="operator_token_fallback",
                        after={k: result[k] for k in ("files_created", "files_skipped", "files_replaced", "db_rows_created", "indexed")},
                        source_route="/api/workspace/seed-fixtures")
        for row in result.get("results", []):
            if row.get("doc_id"):
                al.add_document_attribution(row["doc_id"], "created_by", actor_id, source="primitive_seed",
                                            evidence={"path": row.get("path")})
    except Exception:
        pass
    return result


@router.post("/seed-lineage", summary="Phase 26.3: Seed a lineage relationship between two documents")
def seed_lineage(req: SeedLineageRequest, _operator: str = Depends(require_operator)):
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
def seed_provenance(req: SeedProvenanceRequest, _operator: str = Depends(require_operator)):
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
def get_activity_log(limit: int = Query(100, ge=1), event_type: str | None = None):
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

    _labels.update({
        "import": "File imported",
        "import_skipped_unchanged": "Import skipped unchanged",
        "save": "File written",
        "document_analysis_started": "Analysis started",
        "document_analysis_deterministic_completed": "Review artifact generated",
        "document_analysis_deterministic_failed": "Analysis failed",
        "document_analysis_llm_skipped": "LLM analysis skipped",
        "document_analysis_llm_started": "LLM analysis started",
        "document_analysis_llm_completed": "LLM analysis completed",
        "document_analysis_llm_failed": "LLM analysis failed",
        "document_analysis_queued_for_review": "Review proposal queued",
    })

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
    try:
        full_path = resolve_under_library(doc_path, lib_root)
    except PathBoundaryViolation as exc:
        return {
            "status": "error",
            "endpoint_ok": True,
            "doc_found": True,
            "file_found": False,
            "doc_id": doc["doc_id"],
            "doc_path": doc_path,
            "error": str(exc),
        }
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

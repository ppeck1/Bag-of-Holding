"""app/core/autoindex.py: Startup auto-indexing for Bag of Holding v2.

Phase 12 addition. Provides:
  - Recursive library scan on startup (opt-in)
  - Incremental indexing: skips files whose hash matches DB record
  - Index stats + log tracking
  - Manual re-index trigger via API
  - Never blocks server startup — all errors are caught and counted

Config (via environment variables, extendable to config.toml):
  BOH_LIBRARY              — library root path (default: ./library)
  BOH_AUTO_INDEX           — 'true' to enable auto-index on startup
  BOH_AUTO_INDEX_MAX_FILES — max files to scan (default: 5000)
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

from app.db import connection as db
from app.core import audit

SUPPORTED_EXTENSIONS = {".md", ".txt", ".markdown", ".html", ".htm", ".json"}
AUTO_INDEX_ENABLED  = os.environ.get("BOH_AUTO_INDEX", "false").lower() == "true"
LIBRARY_ROOT        = os.environ.get("BOH_LIBRARY", "./library")
AUTO_INDEX_MAX_FILES = int(os.environ.get("BOH_AUTO_INDEX_MAX_FILES", "5000"))


# ── Table bootstrap ───────────────────────────────────────────────────────────

def _ensure_table():
    """Create autoindex_state table if not exists."""
    conn = db.get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS autoindex_state (
                id             INTEGER PRIMARY KEY DEFAULT 1,
                library_root   TEXT,
                last_run_ts    INTEGER,
                last_scanned   INTEGER DEFAULT 0,
                last_indexed   INTEGER DEFAULT 0,
                last_skipped   INTEGER DEFAULT 0,
                last_failed    INTEGER DEFAULT 0,
                elapsed_ms     INTEGER DEFAULT 0,
                log_json       TEXT    DEFAULT '[]',
                running        INTEGER DEFAULT 0
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ── Public API ────────────────────────────────────────────────────────────────

def get_status() -> dict:
    """Return current auto-index state."""
    _ensure_table()
    row = db.fetchone("SELECT * FROM autoindex_state WHERE id = 1")
    if not row:
        return {
            "enabled": AUTO_INDEX_ENABLED,
            "library_root": LIBRARY_ROOT,
            "last_run_ts": None,
            "last_scanned": 0,
            "last_indexed": 0,
            "last_skipped": 0,
            "last_failed": 0,
            "elapsed_ms": 0,
            "running": False,
        }
    return {
        "enabled":      AUTO_INDEX_ENABLED,
        "library_root": row["library_root"] or LIBRARY_ROOT,
        "last_run_ts":  row["last_run_ts"],
        "last_scanned": row["last_scanned"],
        "last_indexed": row["last_indexed"],
        "last_skipped": row["last_skipped"],
        "last_failed":  row["last_failed"],
        "elapsed_ms":   row["elapsed_ms"],
        "running":      bool(row["running"]),
    }


def scan_library(library_root: str, max_files: int = 5000) -> list[str]:
    """Recursively scan library_root for supported file types."""
    root = Path(library_root).expanduser().resolve()
    if not root.exists():
        return []
    paths = []
    for p in root.rglob("*"):
        if len(paths) >= max_files:
            break
        if (p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
                and not p.name.endswith('.review.md')
                and not p.name.endswith('.review.json')):
            paths.append(str(p))
    return paths


def _file_hash(path: str) -> str:
    """SHA-256 of file contents for change detection."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()



def _classify_failure(exc_type: str, exc_msg: str, path: str) -> tuple[str, str]:
    """Classify an indexing failure and suggest a fix."""
    msg = exc_msg.lower()
    if "relative_to" in msg or "attributeerror" in exc_type.lower():
        return ("path_type_error", "Internal: path passed as string instead of Path object. Report this bug.")
    if "no such file" in msg or "filenotfounderror" in exc_type.lower():
        return ("file_missing", "File was found during scan but is now missing. Check if it was deleted or moved.")
    if "unicodedecodeerror" in exc_type.lower() or "codec" in msg:
        return ("encoding_error", f"File '{path}' has non-UTF-8 encoding. Re-save as UTF-8 or remove.")
    if "permissionerror" in exc_type.lower():
        return ("permission_denied", f"Cannot read '{path}'. Check file permissions.")
    if "yaml" in msg or "scanner" in msg or "mapping" in msg:
        return ("frontmatter_parse_error", "YAML frontmatter is malformed. Check for tab characters, bad indentation, or unclosed quotes.")
    if "canonical" in msg and "overwrite" in msg:
        return ("canon_protection", "File is attempting to overwrite an existing canonical document. Use the governance workflow.")
    if "json" in msg or "jsondecode" in exc_type.lower():
        return ("json_parse_error", "JSON is malformed. Run the file through a JSON validator.")
    if "database" in msg or "sqlite" in msg or "operationalerror" in exc_type.lower():
        return ("db_error", "Database write failed. Try resetting the workspace if the error persists.")
    return ("unknown_error", f"Unexpected {exc_type}. Check the error message and file content.")

def run_auto_index(
    library_root: Optional[str] = None,
    max_files: int = AUTO_INDEX_MAX_FILES,
    changed_only: bool = True,
) -> dict:
    """Scan and index the library. Returns stats dict.

    Uses indexer.index_file() for consistency with manual indexing.
    Catches per-file errors — a single broken file never aborts the run.
    Server startup is never blocked: call this in a background thread or
    FastAPI startup event with try/except around the whole call.
    """
    _ensure_table()
    from app.services import indexer as crawler

    root = library_root or LIBRARY_ROOT
    start_ts = int(time.time())
    start_ms = time.monotonic()

    # Mark as running
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO autoindex_state (id, library_root, running) VALUES (1, ?, 1)",
            (root,),
        )
        conn.commit()
    finally:
        conn.close()

    paths   = scan_library(root, max_files)
    scanned = len(paths)
    indexed = skipped = failed = 0
    log: list[dict] = []

    root_path = Path(root).resolve()
    for path in paths:
        path_obj = Path(path)
        rel = path_obj.relative_to(root_path).as_posix() if path_obj.is_absolute() else path
        try:
            if changed_only:
                existing = db.fetchone("SELECT text_hash FROM docs WHERE path = ?", (rel,))
                if existing:
                    current_hash = _file_hash(path)
                    if existing["text_hash"] and existing["text_hash"] == current_hash:
                        skipped += 1
                        continue
            result = crawler.index_file(path_obj, root_path)
            indexed += 1
            lint = result.get("lint_errors", [])
            entry = {"path": rel, "status": "indexed"}
            if lint:
                entry["lint_warnings"] = lint[:3]

            # Phase 26.5 Fix B: run analysis pipeline after successful index
            if result.get("indexed") and result.get("doc_id"):
                try:
                    from app.core.document_analysis_pipeline import analyze_document_after_index
                    analysis = analyze_document_after_index(
                        doc_id=result["doc_id"],
                        file_path=result.get("path", rel),
                        library_root=str(root_path),
                        run_deterministic=os.environ.get(
                            "BOH_DETERMINISTIC_REVIEW_ON_INDEX", "true").lower() != "false",
                        run_llm=os.environ.get(
                            "BOH_LLM_REVIEW_ON_INDEX", "false").lower() == "true"
                            or os.environ.get(
                            "BOH_ANALYZE_ON_INDEX", "false").lower() == "true",
                        actor_id="system:autoindex",
                    )
                    entry["analysis"] = {
                        "deterministic_review": analysis["deterministic_review"],
                        "llm_analysis": {
                            "attempted": analysis["llm_analysis"]["attempted"],
                            "disabled": analysis["llm_analysis"]["disabled"],
                        },
                    }
                except Exception as ae:
                    entry["analysis"] = {"error": str(ae)[:100]}

            log.append(entry)
        except Exception as exc:
            failed += 1
            exc_type = type(exc).__name__
            reason, fix = _classify_failure(exc_type, str(exc), rel)
            log.append({
                "path": rel,
                "status": "failed",
                "error": str(exc)[:200],
                "error_type": exc_type,
                "reason": reason,
                "recommended_fix": fix,
            })

    elapsed_ms = int((time.monotonic() - start_ms) * 1000)

    # Persist stats (keep last 50 log lines)
    conn = db.get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO autoindex_state
               (id, library_root, last_run_ts, last_scanned, last_indexed,
                last_skipped, last_failed, elapsed_ms, log_json, running)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (root, start_ts, scanned, indexed, skipped, failed,
             elapsed_ms, json.dumps(log[-50:])),
        )
        conn.commit()
    finally:
        conn.close()

    audit.log_event(
        "index",
        actor_type="system",
        detail=json.dumps({
            "auto": True, "root": root,
            "scanned": scanned, "indexed": indexed,
            "skipped": skipped, "failed": failed,
        }),
    )

    return {
        "library_root": root,
        "scanned": scanned,
        "indexed": indexed,
        "skipped": skipped,
        "failed":  failed,
        "elapsed_ms": elapsed_ms,
        "log": log[-20:],
    }


def run_on_startup_if_enabled() -> Optional[dict]:
    """Called from main.py startup event. No-op if BOH_AUTO_INDEX != 'true'.
    Always safe to call — never raises.
    """
    if not AUTO_INDEX_ENABLED:
        return None
    try:
        return run_auto_index(changed_only=True)
    except Exception as exc:
        # Log but never crash startup
        try:
            audit.log_event(
                "index",
                actor_type="system",
                detail=json.dumps({"auto": True, "error": str(exc)[:200]}),
            )
        except Exception:
            pass
        return {"error": str(exc)}


def get_failure_log(library_root: str | None = None) -> list[dict]:
    """Return the per-file failure log from the last autoindex run."""
    _ensure_table()
    row = db.fetchone("SELECT log_json FROM autoindex_state WHERE id = 1")
    if not row or not row["log_json"]:
        return []
    import json as _json
    try:
        entries = _json.loads(row["log_json"])
        return [e for e in entries if e.get("status") == "failed"]
    except Exception:
        return []


def get_full_log(library_root: str | None = None) -> list[dict]:
    """Return the complete per-file log from the last autoindex run."""
    _ensure_table()
    row = db.fetchone("SELECT log_json FROM autoindex_state WHERE id = 1")
    if not row or not row["log_json"]:
        return []
    import json as _json
    try:
        return _json.loads(row["log_json"])
    except Exception:
        return []

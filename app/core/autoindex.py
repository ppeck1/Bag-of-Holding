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

SUPPORTED_EXTENSIONS = {".md", ".txt", ".markdown"}
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
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
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

    for path in paths:
        try:
            if changed_only:
                existing = db.fetchone("SELECT text_hash FROM docs WHERE path = ?", (path,))
                if existing:
                    current_hash = _file_hash(path)
                    if existing["text_hash"] and existing["text_hash"] == current_hash:
                        skipped += 1
                        continue
            crawler.index_file(path, root)
            indexed += 1
            log.append({"path": path, "status": "indexed"})
        except Exception as exc:
            failed += 1
            log.append({"path": path, "status": "failed", "error": str(exc)[:120]})

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

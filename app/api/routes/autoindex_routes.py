"""app/api/routes/autoindex_routes.py: Auto-index API endpoints.

Phase 26.3 additions:
  GET  /api/autoindex/failures  — per-file failure log with reasons + recommended fixes
  GET  /api/autoindex/report    — exportable full run report (JSON)
  GET  /api/autoindex/log       — full log (indexed + skipped + failed)
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import autoindex
from app.core.auth import require_operator
from app.core.fs_boundary import PathBoundaryViolation, ensure_request_root_allowed

router = APIRouter(prefix="/api")

LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")


class AutoIndexRequest(BaseModel):
    library_root: Optional[str] = None
    max_files: int = 5000
    changed_only: bool = True
    include_scratch: bool = False


@router.get("/autoindex/status", summary="Get auto-index state", tags=["system"])
def get_autoindex_status():
    return autoindex.get_status()


@router.post("/autoindex/run", summary="Trigger a library index run", tags=["system"])
def trigger_autoindex(req: AutoIndexRequest, _operator: str = Depends(require_operator)):
    """Scan and index the library. Skips unchanged files when changed_only=True."""
    try:
        root = ensure_request_root_allowed(req.library_root, os.environ.get("BOH_LIBRARY", "./library"))
    except PathBoundaryViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    result = autoindex.run_auto_index(
        library_root=str(root),
        max_files=req.max_files,
        changed_only=req.changed_only,
        include_scratch=req.include_scratch,
    )
    return result


@router.get("/autoindex/failures", summary="Phase 26.3: Per-file failure log with reasons and recommended fixes", tags=["system"])
def get_autoindex_failures():
    """Return per-file failure details from the last autoindex run.

    Each entry includes:
        path              — relative file path
        error             — raw exception message
        error_type        — exception class name
        reason            — classified failure reason
        recommended_fix   — plain-English fix suggestion
    """
    failures = autoindex.get_failure_log()
    return {
        "failure_count": len(failures),
        "failures": failures,
        "guidance": (
            "Each entry shows the exact file, error type, and a recommended fix. "
            "Common fixes: re-save files as UTF-8, validate YAML frontmatter, "
            "check file permissions, or run a workspace reset if DB errors persist."
        ),
    }


@router.get("/autoindex/log", summary="Phase 26.3: Full per-file log (all statuses)", tags=["system"])
def get_autoindex_log():
    """Return the complete per-file log from the last autoindex run (indexed + failed)."""
    full_log = autoindex.get_full_log()
    indexed  = [e for e in full_log if e.get("status") == "indexed"]
    failed   = [e for e in full_log if e.get("status") == "failed"]
    return {
        "total_entries": len(full_log),
        "indexed_count": len(indexed),
        "failed_count": len(failed),
        "log": full_log,
    }


@router.get("/autoindex/report", summary="Phase 26.3: Exportable reindex diagnostic report", tags=["system"])
def get_autoindex_report():
    """Return a full diagnostic report suitable for export.

    Includes: run stats, all failures with reasons, all lint warnings,
    recommended next actions, and workspace health summary.
    """
    status = autoindex.get_status()
    full_log = autoindex.get_full_log()
    failures = [e for e in full_log if e.get("status") == "failed"]
    with_warnings = [e for e in full_log if e.get("lint_warnings")]

    # Group failures by reason
    by_reason: dict = {}
    for f in failures:
        reason = f.get("reason", "unknown_error")
        by_reason.setdefault(reason, []).append(f["path"])

    # Recommended next actions
    actions = []
    if status.get("last_failed", 0) > 0:
        actions.append(f"CRITICAL: {status['last_failed']} file(s) failed to index. See failures list.")
    if any(r == "frontmatter_parse_error" for r in by_reason):
        actions.append("Fix YAML frontmatter in affected files (check for tabs, bad indentation, unclosed quotes).")
    if any(r == "encoding_error" for r in by_reason):
        actions.append("Re-save files with encoding errors as UTF-8.")
    if any(r == "file_missing" for r in by_reason):
        actions.append("Remove stale DB references or re-add missing files.")
    if not actions:
        actions.append("No critical issues. Library indexed cleanly.")

    return {
        "report_type": "autoindex_diagnostic",
        "run_stats": {
            "library_root": status.get("library_root"),
            "last_run_ts": status.get("last_run_ts"),
            "scanned": status.get("last_scanned", 0),
            "indexed": status.get("last_indexed", 0),
            "skipped": status.get("last_skipped", 0),
            "failed": status.get("last_failed", 0),
            "elapsed_ms": status.get("elapsed_ms", 0),
        },
        "failures": failures,
        "manifest": [
            {
                "relative_path": e.get("relative_path") or e.get("path"),
                "classification": e.get("classification", "unknown"),
                "action": e.get("action") or e.get("status"),
                "reason": e.get("reason", ""),
                "lint_warning_count": e.get("lint_warning_count", len(e.get("lint_warnings", []) or [])),
            }
            for e in full_log
        ],
        "failures_by_reason": by_reason,
        "files_with_lint_warnings": len(with_warnings),
        "recommended_actions": actions,
        "health": "critical" if failures else ("warning" if with_warnings else "ok"),
    }

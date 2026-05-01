"""app/core/document_analysis_pipeline.py

Phase 26.5 — Fix A: First-class document analysis pipeline.

Bridges the gap between:
    1. autoindex/indexer   — file → DB record
    2. reviewer            — DB record → deterministic review artifact
    3. ollama.invoke       — artifact → optional LLM analysis
    4. llm_queue           — LLM analysis → review queue proposal

Previously these three subsystems were completely disconnected.
Indexing succeeded but no analysis was ever triggered or logged.

Pipeline contract:

    file import
    → index_file()
    → analyze_document_after_index()
        → deterministic review artifact (always, unless disabled)
        → optional LLM analysis (only if BOH_ANALYZE_ON_INDEX + Ollama enabled)
        → optional review queue enqueue
    → audit events at every stage

Return shape:
    {
        "doc_id": "...",
        "file_path": "...",
        "deterministic_review": {
            "attempted": True,
            "success": True,
            "artifact_path": "...",
            "topics_extracted": 5,
            "defs_extracted": 2,
            "error": None,
        },
        "llm_analysis": {
            "attempted": False,
            "success": False,
            "invocation_id": None,
            "queue_id": None,
            "disabled": True,
            "error": None,
        }
    }

Environment flags:
    BOH_DETERMINISTIC_REVIEW_ON_INDEX=true   (default: true)
    BOH_LLM_REVIEW_ON_INDEX=false            (default: false)
    BOH_ANALYZE_ON_INDEX=false               (umbrella flag, enables both if true)

Governance invariants (non-negotiable):
    - LLM output is ALWAYS non_authoritative
    - LLM output may ONLY enqueue a review proposal
    - Canonical promotion remains blocked without custodian workflow
    - Review artifacts may NOT overwrite source documents
    - Every stage is observable in audit logs
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from app.db import connection as db
from app.core.audit import log_event

# ---------------------------------------------------------------------------
# Environment flags
# ---------------------------------------------------------------------------

def _det_review_enabled() -> bool:
    """Deterministic review is on by default; BOH_DETERMINISTIC_REVIEW_ON_INDEX=false turns it off."""
    umbrella = os.environ.get("BOH_ANALYZE_ON_INDEX", "").lower()
    specific = os.environ.get("BOH_DETERMINISTIC_REVIEW_ON_INDEX", "true").lower()
    if umbrella == "false":
        return False
    return specific != "false"

def _llm_enabled() -> bool:
    """LLM analysis is off by default; BOH_LLM_REVIEW_ON_INDEX=true or BOH_ANALYZE_ON_INDEX=true enables it."""
    umbrella = os.environ.get("BOH_ANALYZE_ON_INDEX", "false").lower()
    specific = os.environ.get("BOH_LLM_REVIEW_ON_INDEX", "false").lower()
    return umbrella == "true" or specific == "true"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_document_after_index(
    *,
    doc_id: str,
    file_path: str,
    library_root: str,
    run_deterministic: bool | None = None,
    run_llm: bool | None = None,
    actor_id: str = "system:autoindex",
) -> dict[str, Any]:
    """Run the full post-index analysis pipeline for a single document.

    Args:
        doc_id:          The indexed document's ID in the docs table.
        file_path:       Library-relative path to the source file.
        library_root:    Absolute path to the library root.
        run_deterministic: Override env flag. None = use env.
        run_llm:         Override env flag. None = use env.
        actor_id:        Actor identity for audit events.

    Returns:
        Pipeline result dict (see module docstring for shape).

    Never raises. All errors are captured in the result dict.
    """
    if run_deterministic is None:
        run_deterministic = _det_review_enabled()
    if run_llm is None:
        run_llm = _llm_enabled()

    result: dict[str, Any] = {
        "doc_id": doc_id,
        "file_path": file_path,
        "deterministic_review": {
            "attempted": False,
            "success": False,
            "artifact_path": None,
            "topics_extracted": 0,
            "defs_extracted": 0,
            "error": None,
        },
        "llm_analysis": {
            "attempted": False,
            "success": False,
            "invocation_id": None,
            "queue_id": None,
            "disabled": not run_llm,
            "error": None,
        },
    }

    _audit("document_analysis_started", actor_id, doc_id, file_path, {
        "run_deterministic": run_deterministic,
        "run_llm": run_llm,
    })

    # ── Stage 1: Deterministic Review ───────────────────────────────────────
    if run_deterministic:
        result["deterministic_review"]["attempted"] = True
        try:
            from app.services.reviewer import generate_review_artifact
            artifact = generate_review_artifact(file_path, library_root)

            if "error" in artifact:
                result["deterministic_review"]["error"] = artifact["error"]
                _audit("document_analysis_deterministic_failed", actor_id, doc_id, file_path,
                       {"error": artifact["error"]})
            else:
                # Resolve artifact path
                art_path = None
                try:
                    from app.services.reviewer import _artifact_path
                    art_path = str(_artifact_path(file_path, library_root))
                except Exception:
                    pass

                result["deterministic_review"].update({
                    "success": True,
                    "artifact_path": art_path,
                    "topics_extracted": len(artifact.get("extracted_topics", [])),
                    "defs_extracted": len(artifact.get("extracted_definitions", [])),
                })
                _audit("document_analysis_deterministic_completed", actor_id, doc_id, file_path,
                       {
                           "artifact_path": art_path,
                           "topics_extracted": result["deterministic_review"]["topics_extracted"],
                           "defs_extracted": result["deterministic_review"]["defs_extracted"],
                       })
        except Exception as exc:
            err = str(exc)[:200]
            result["deterministic_review"]["error"] = err
            _audit("document_analysis_deterministic_failed", actor_id, doc_id, file_path,
                   {"error": err})

    # ── Stage 2: Optional LLM Analysis ──────────────────────────────────────
    if not run_llm:
        result["llm_analysis"]["disabled"] = True
        _audit("document_analysis_llm_skipped", actor_id, doc_id, file_path,
               {"reason": "BOH_LLM_REVIEW_ON_INDEX not enabled"})
    else:
        result["llm_analysis"]["attempted"] = True
        result["llm_analysis"]["disabled"] = False
        try:
            from app.core import ollama as ollama_core

            # Check availability before attempting
            avail = ollama_core.check_availability()
            if not avail.get("available"):
                result["llm_analysis"]["error"] = "Ollama not available"
                result["llm_analysis"]["disabled"] = True
                _audit("document_analysis_llm_skipped", actor_id, doc_id, file_path,
                       {"reason": "Ollama not available", "detail": avail.get("error", "")})
            else:
                # Read source text (capped at Ollama content limit)
                lib = Path(library_root).resolve()
                src = (lib / file_path).resolve()
                if not src.exists():
                    raise FileNotFoundError(f"Source file not found: {src}")

                text = src.read_text(encoding="utf-8", errors="replace")
                max_chars = int(os.environ.get("BOH_OLLAMA_MAX_CONTENT", "20000"))
                text_capped = text[:max_chars]

                _audit("document_analysis_llm_started", actor_id, doc_id, file_path,
                       {"content_chars": len(text_capped), "model": "default"})

                invocation_result = ollama_core.invoke(
                    task_type="document_review",
                    content=text_capped,
                    doc_id=doc_id,
                    scope={"docs": [doc_id], "paths": [file_path]},
                )

                inv_id = invocation_result.get("invocation_id")
                result["llm_analysis"]["invocation_id"] = inv_id

                if invocation_result.get("status") not in ("ok", "success", None):
                    result["llm_analysis"]["error"] = invocation_result.get("error", "LLM invocation failed")
                    _audit("document_analysis_llm_failed", actor_id, doc_id, file_path,
                           {"error": result["llm_analysis"]["error"]})
                else:
                    result["llm_analysis"]["success"] = True
                    _audit("document_analysis_llm_completed", actor_id, doc_id, file_path,
                           {"invocation_id": inv_id})

                    # Enqueue for review if response exists
                    resp = invocation_result.get("response_json") or invocation_result.get("response")
                    if resp:
                        try:
                            from app.core import llm_queue
                            queue_id = llm_queue.enqueue(
                                proposed=resp if isinstance(resp, dict) else {"summary": str(resp)[:500]},
                                doc_id=doc_id,
                                file_path=file_path,
                                model=invocation_result.get("model"),
                                invocation_id=inv_id,
                            )
                            result["llm_analysis"]["queue_id"] = queue_id
                            _audit("document_analysis_queued_for_review", actor_id, doc_id, file_path,
                                   {"queue_id": queue_id, "invocation_id": inv_id})
                        except Exception as qe:
                            result["llm_analysis"]["error"] = f"Queue enqueue failed: {qe}"

        except Exception as exc:
            err = str(exc)[:200]
            result["llm_analysis"]["error"] = err
            _audit("document_analysis_llm_failed", actor_id, doc_id, file_path,
                   {"error": err})

    return result


def analyze_batch(
    doc_ids: list[str],
    library_root: str,
    actor_id: str = "system:batch",
    run_deterministic: bool = True,
    run_llm: bool = False,
) -> list[dict[str, Any]]:
    """Run the analysis pipeline for a batch of doc IDs.

    Looks up each doc's file_path from the docs table.
    Skips docs not found in DB.
    Returns one result per successfully processed doc.
    """
    results = []
    for doc_id in doc_ids:
        row = db.fetchone("SELECT path FROM docs WHERE doc_id=?", (doc_id,))
        if not row:
            results.append({
                "doc_id": doc_id,
                "file_path": None,
                "error": "doc not found in DB",
            })
            continue
        r = analyze_document_after_index(
            doc_id=doc_id,
            file_path=row["path"],
            library_root=library_root,
            run_deterministic=run_deterministic,
            run_llm=run_llm,
            actor_id=actor_id,
        )
        results.append(r)
    return results


def get_analysis_status(library_root: str | None = None) -> dict[str, Any]:
    """Return a summary of the analysis pipeline status.

    Counts:
        - total docs indexed
        - docs with deterministic review artifacts on disk
        - docs missing review artifacts
        - LLM invocation count
        - pending LLM queue items
    """
    db.init_db()
    lib_root = library_root or os.environ.get("BOH_LIBRARY", "./library")

    # Total docs
    try:
        row = db.fetchone("SELECT COUNT(*) as n FROM docs")
        total_docs = row["n"] if row else 0
    except Exception:
        total_docs = 0

    # Docs with artifacts on disk
    artifacts_on_disk = 0
    missing_artifacts = 0
    try:
        rows = db.fetchall("SELECT path FROM docs")
        lib = Path(lib_root).resolve()
        from app.services.reviewer import _artifact_path, _safe_join_library
        for row in rows:
            p = row["path"] if row else ""
            if not p:
                continue
            try:
                art = _artifact_path(p, lib_root)
                if art.exists():
                    artifacts_on_disk += 1
                else:
                    missing_artifacts += 1
            except Exception:
                missing_artifacts += 1
    except Exception:
        pass

    # LLM invocations
    try:
        inv_row = db.fetchone("SELECT COUNT(*) as n FROM llm_invocations")
        invocations_total = inv_row["n"] if inv_row else 0
    except Exception:
        invocations_total = 0

    # LLM queue
    try:
        q_row = db.fetchone("SELECT COUNT(*) as n FROM llm_review_queue WHERE status='pending'")
        pending_queue = q_row["n"] if q_row else 0
    except Exception:
        pending_queue = 0

    # Last analysis events
    try:
        events = db.fetchall(
            """SELECT event_ts, event_type, doc_id, detail FROM audit_log
               WHERE event_type LIKE 'document_analysis%'
               ORDER BY event_ts DESC LIMIT 10"""
        )
        last_events = [
            {"ts": e["event_ts"], "event_type": e["event_type"], "doc_id": e["doc_id"]}
            for e in events
        ]
    except Exception:
        last_events = []

    # Ollama status
    ollama_enabled = os.environ.get("BOH_OLLAMA_ENABLED", "").lower() == "true"
    llm_analyze_on_index = _llm_enabled()
    det_analyze_on_index = _det_review_enabled()

    return {
        "deterministic_review": {
            "enabled_on_index": det_analyze_on_index,
            "artifacts_total": artifacts_on_disk,
            "missing_artifacts": missing_artifacts,
            "total_docs": total_docs,
        },
        "llm": {
            "enabled": ollama_enabled,
            "analyze_on_index": llm_analyze_on_index,
            "available": False,  # don't ping Ollama in status — too slow
            "invocations_total": invocations_total,
            "pending_queue": pending_queue,
        },
        "last_analysis_events": last_events,
        "note": (
            "Deterministic review extracts topics/defs without Ollama. "
            "LLM analysis requires BOH_OLLAMA_ENABLED=true and a running Ollama instance. "
            "Both are non-authoritative and require explicit user confirmation to apply."
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audit(event_type: str, actor_id: str, doc_id: str, file_path: str,
           detail: dict[str, Any]) -> None:
    try:
        log_event(
            event_type,
            actor_type="system",
            actor_id=actor_id,
            doc_id=doc_id,
            detail=json.dumps({**detail, "file_path": file_path}),
        )
    except Exception:
        pass

"""Governed intake→retrieval promotion service (WO-2 runtime; DEC-0003 / DEC-0004).

Doctrine: LLM proposes, human governs, system audits. Promotion is an operator-gated mutation,
never an ingestion side effect. Eligibility is fail-closed and derived ONLY from durable rows
(`intake_handoffs` is the promotability source of truth — never trace-event scans). Promoted docs
are advisory: `canon_eligible` stays 0, `corpus_class='CORPUS_CLASS:PROMOTED_INTAKE'` marks them
for the shared exposure predicate (`app/core/promoted_exposure.py`), and demotion is reversible
and scoped strictly by the promotion ledger's provenance keys.

Atomicity note: the library file write + `index_file` commit independently of the ledger
transaction (cross-store, like preservation vs SQLite in WO-1). The ledger row is the authority;
`doc_id` is deterministic per `source_revision_id`, so a crash between indexing and the ledger
insert is healed by an idempotent re-promote (INSERT OR REPLACE on docs; ledger single-winner).
Exposure safety across every crash window: the promoted frontmatter declares
`type/document_class = promoted_intake`, and `corpus.classify()` maps that to
`CORPUS_CLASS:PROMOTED_INTAKE`, so a doc indexed by ANY path (promotion, orphan re-scan, retry)
carries the exclusion marker from its first instant — an interrupted promotion can leave an inert
marked doc or an inert managed file, never an exposed one.

Handoff-event semantics: each pipeline handoff EVENT gets its own `intake_handoffs` row with a
unique row id (the HandoffPacket's deterministic per-capability id would collide on
reprocess/replay). Multiple ready rows per capability are expected; selection everywhere is
latest-wins (`created_at DESC, handoff_id DESC`).

Path containment: artifact reads must resolve inside BOH_DATA_ROOT; managed writes must resolve
inside `<library>/promoted_intake/` — both checked on RESOLVED paths (symlinks/junctions and
`..`/drive tricks are therefore rejected by containment, not by string inspection).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

from app.core import promoted_exposure
from app.db import connection as db
from app.services.intake import intake_writer as W
from app.services.intake import trace as trace_module
from app.services.intake.clock import utc_now_iso
from app.services.intake.source_revision import canonicalize_source_ref

PROMOTED_SUBDIR = "promoted_intake"
_ACTOR = "local_operator"  # server-set, never accepted from a client


# ── helpers ──────────────────────────────────────────────────────────────────────


def _library_root() -> Path:
    from app.core.input_surface import get_library_root
    return Path(get_library_root())


def _is_within(child: Path, parent: Path) -> bool:
    """Resolved containment check (Windows case-fold; follows symlinks/junctions)."""
    try:
        c = str(child.resolve()).casefold()
        p = str(parent.resolve()).casefold().rstrip("\\/")
    except OSError:
        return False
    return c == p or c.startswith(p + os.sep)


def _artifact_path_or_reason(output_path: str) -> tuple[Path | None, str | None]:
    """Resolve a normalized-artifact path (stored relative to the data root, Phase 5) and
    fail closed unless the RESOLVED path is inside BOH_DATA_ROOT."""
    root = os.environ.get("BOH_DATA_ROOT", "")
    if not root:
        return None, "data_root_not_configured"
    p = Path(output_path)
    if not p.is_absolute():
        p = Path(root) / p
    if not _is_within(p, Path(root)):
        return None, "artifact_path_outside_data_root"
    return p.resolve(), None


def _promoted_dest(doc_id: str) -> Path:
    """Managed destination strictly beneath <library>/promoted_intake/ — containment-checked
    on the resolved path so `..` components, separators, or symlinked parents cannot escape."""
    managed = _library_root() / PROMOTED_SUBDIR
    dest = managed / f"{doc_id}.md"
    if not _is_within(dest, managed):
        raise ValueError("destination_escapes_managed_subdir")
    return dest


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _latest_ready_handoff(conn, *, source_revision_id: str | None = None,
                          intake_capability_id: str | None = None):
    where, arg = (("h.source_revision_id = ?", source_revision_id)
                  if source_revision_id else
                  ("h.intake_capability_id = ?", intake_capability_id))
    return conn.execute(
        f"SELECT * FROM intake_handoffs h WHERE {where} AND h.handoff_ready = 1 "
        "ORDER BY h.created_at DESC, h.handoff_id DESC LIMIT 1",
        (arg,),
    ).fetchone()


def _eligibility_reasons(conn, handoff) -> list[str]:
    """Fail-closed eligibility per the WO-2 proposal + DEC-0004; every reason is structured.
    The capability/artifact existence checks double as the §2b dangling-reference invariants."""
    reasons: list[str] = []

    rev = conn.execute(
        "SELECT lifecycle_state FROM intake_source_revisions WHERE source_revision_id = ?",
        (handoff["source_revision_id"],),
    ).fetchone()
    if rev is None:
        reasons.append("revision_missing")
    elif rev["lifecycle_state"] != "complete":
        reasons.append(f"revision_not_complete:{rev['lifecycle_state']}")

    run = conn.execute("SELECT lifecycle_state FROM intake_runs WHERE run_id = ?",
                       (handoff["intake_run_id"],)).fetchone()
    if run is None:
        reasons.append("run_missing")

    cap = conn.execute(
        "SELECT queryable, canon_eligible, safety_lane FROM intake_capabilities "
        "WHERE intake_capability_id = ?",
        (handoff["intake_capability_id"],),
    ).fetchone()
    if cap is None:
        reasons.append("capability_missing")
    else:
        if not cap["queryable"]:
            reasons.append("not_queryable")
        if cap["canon_eligible"]:
            reasons.append("canon_eligible_anomaly")
        if cap["safety_lane"] != "accept":
            reasons.append(f"safety_lane_not_accept:{cap['safety_lane']}")

    art = conn.execute(
        "SELECT output_path, output_hash_sha256 FROM intake_normalized_artifacts "
        "WHERE normalized_artifact_id = ?",
        (handoff["normalized_artifact_id"],),
    ).fetchone()
    if art is None:
        reasons.append("normalized_artifact_missing")
    else:
        path, why = _artifact_path_or_reason(art["output_path"])
        if why:
            reasons.append(why)
        elif not path.is_file():
            reasons.append("normalized_file_missing")
        elif _sha256_file(path) != art["output_hash_sha256"]:
            reasons.append("normalized_hash_mismatch")
    return reasons


def _active_promotion(conn, source_revision_id: str):
    return conn.execute(
        "SELECT * FROM intake_promotions WHERE source_revision_id = ? AND status = 'active'",
        (source_revision_id,),
    ).fetchone()


def _doc_id_for(source_revision_id: str) -> str:
    return f"promoted-{source_revision_id[:16]}"


def _compose_promoted_doc(handoff, content: str, doc_id: str, title: str) -> str:
    safe_title = title.replace('"', "'")
    front = (
        "---\n"
        "boh:\n"
        f'  id: "{doc_id}"\n'
        f'  document_id: "{doc_id}"\n'
        f'  title: "{safe_title}"\n'
        '  purpose: "Promoted intake artifact (advisory; human-promoted, not canonized)"\n'
        '  type: "promoted_intake"\n'
        '  document_class: "promoted_intake"\n'
        '  status: "draft"\n'
        '  canonical_layer: "supporting"\n'
        '  authority_state: "draft"\n'
        '  review_state: "none"\n'
        '  project: "Promoted Intake"\n'
        '  version: "1.0.0"\n'
        f'  updated: "{utc_now_iso()}"\n'
        f'  source_hash: "{handoff["normalized_artifact_id"]}"\n'
        "  provenance:\n"
        '    mode: "intake_promotion"\n'
        f'    source_revision_id: "{handoff["source_revision_id"]}"\n'
        f'    intake_capability_id: "{handoff["intake_capability_id"]}"\n'
        f'    handoff_id: "{handoff["handoff_id"]}"\n'
        '  topics: ["promoted_intake"]\n'
        "---\n\n"
    )
    return front + content


def _audit(conn, event_type: str, detail: dict) -> None:
    conn.execute(
        "INSERT INTO audit_log (event_ts, event_type, actor_type, actor_id, detail) "
        "VALUES (?,?,?,?,?)",
        (int(time.time()), event_type, "operator", _ACTOR, json.dumps(detail)),
    )


def _persist_trace(event_type: str, capability_id: str | None, detail: dict) -> None:
    te = trace_module.emit(event_type, intake_capability_id=capability_id, detail=detail)
    conn = db.get_conn()
    try:
        W.persist_stage_transition(conn, trace_events=[te])
    finally:
        conn.close()


# ── public API ───────────────────────────────────────────────────────────────────


def list_promotable() -> list[dict]:
    """Read-only: latest ready handoff per capability, with eligibility + promotion status."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT h.* FROM intake_handoffs h "
            "WHERE h.handoff_ready = 1 AND h.created_at = ("
            "  SELECT MAX(h2.created_at) FROM intake_handoffs h2 "
            "  WHERE h2.intake_capability_id = h.intake_capability_id) "
            "ORDER BY h.created_at",
        ).fetchall()
        out = []
        for h in rows:
            reasons = _eligibility_reasons(conn, h)
            active = _active_promotion(conn, h["source_revision_id"])
            out.append({
                "handoff_id": h["handoff_id"],
                "intake_capability_id": h["intake_capability_id"],
                "source_revision_id": h["source_revision_id"],
                "normalized_artifact_id": h["normalized_artifact_id"],
                "normalized_output_type": h["normalized_output_type"],
                "normalized_output_profile": h["normalized_output_profile"],
                "eligible": not reasons and active is None,
                "reasons": reasons,
                "already_promoted_doc_id": active["doc_id"] if active else None,
            })
        return out
    finally:
        conn.close()


def promote(*, source_revision_id: str | None = None,
            intake_capability_id: str | None = None,
            batch_id: str | None = None,
            actor_id: str = _ACTOR) -> dict:
    """Operator-gated, fail-closed, idempotent promotion of ONE revision's normalized artifact."""
    if not (source_revision_id or intake_capability_id):
        return {"promoted": False, "reasons": ["no_target_specified"]}

    conn = db.get_conn()
    try:
        handoff = _latest_ready_handoff(conn, source_revision_id=source_revision_id,
                                        intake_capability_id=intake_capability_id)
        if handoff is None:
            return {"promoted": False, "reasons": ["no_ready_handoff"]}
        srid = handoff["source_revision_id"]

        existing = _active_promotion(conn, srid)
        if existing is not None:
            return {"promoted": False, "idempotent": True,
                    "doc_id": existing["doc_id"], "promotion_id": existing["promotion_id"]}

        reasons = _eligibility_reasons(conn, handoff)
        if reasons:
            return {"promoted": False, "reasons": reasons}

        art = conn.execute(
            "SELECT output_path, output_hash_sha256 FROM intake_normalized_artifacts "
            "WHERE normalized_artifact_id = ?", (handoff["normalized_artifact_id"],),
        ).fetchone()
        rev = conn.execute(
            "SELECT canonical_source_ref FROM intake_source_revisions "
            "WHERE source_revision_id = ?", (srid,),
        ).fetchone()
        doc_id = _doc_id_for(srid)
        title = Path(rev["canonical_source_ref"]).name

        # Managed library write inside the BOH_LIBRARY boundary, then the EXISTING indexing
        # path. Any I/O or indexing failure here fails CLOSED with a structured reason; the
        # classify() rule guarantees a partially-indexed doc is already marker-excluded, and a
        # deterministic retry reconciles every partial state (same doc_id, same dest file).
        try:
            artifact_path, _why = _artifact_path_or_reason(art["output_path"])
            content = artifact_path.read_text(encoding="utf-8", errors="replace")
            dest = _promoted_dest(doc_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(_compose_promoted_doc(handoff, content, doc_id, title),
                            encoding="utf-8")
            from app.services.indexer import index_file
            index_file(dest, _library_root())
        except Exception as exc:
            logger.exception("promotion I/O/indexing failed for %s", srid)
            return {"promoted": False,
                    "reasons": [f"promotion_io_failed:{type(exc).__name__}"]}

        now = utc_now_iso()
        promotion_id = f"promo_{uuid.uuid4().hex[:20]}"
        try:
            with conn:
                # Advisory marker is set explicitly (never by the classifier) — the shared
                # exposure predicate keys on it. canon_eligible is untouched (stays 0).
                conn.execute(
                    "UPDATE docs SET corpus_class = ? WHERE doc_id = ?",
                    (promoted_exposure.PROMOTED_CORPUS_CLASS, doc_id),
                )
                # Supersede: a prior ACTIVE promotion of the SAME source path under a different
                # revision identity is marked superseded (never silently mutated/deleted).
                prior = conn.execute(
                    "SELECT p.promotion_id, p.doc_id FROM intake_promotions p "
                    "JOIN intake_source_revisions r ON r.source_revision_id = p.source_revision_id "
                    "WHERE p.status = 'active' AND r.canonical_source_ref = ? "
                    "AND p.source_revision_id <> ?",
                    (rev["canonical_source_ref"], srid),
                ).fetchone()
                supersedes = None
                if prior is not None:
                    supersedes = prior["promotion_id"]
                    conn.execute(
                        "UPDATE intake_promotions SET status='superseded', updated_at=? "
                        "WHERE promotion_id = ?", (now, supersedes))
                    conn.execute(
                        "INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail) "
                        "VALUES (?,?,?,?,?)",
                        (doc_id, prior["doc_id"], "supersedes", int(time.time()),
                         "intake promotion supersession"))
                conn.execute(
                    "INSERT INTO intake_promotions (promotion_id, promotion_batch_id, "
                    "source_revision_id, intake_capability_id, handoff_id, normalized_artifact_id, "
                    "doc_id, normalized_hash, normalized_output_type, normalized_output_profile, "
                    "adapter_id, adapter_version, adapter_registry_version, policy_snapshot_hash, "
                    "status, supersedes_promotion_id, promoted_by, promoted_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (promotion_id, batch_id, srid, handoff["intake_capability_id"],
                     handoff["handoff_id"], handoff["normalized_artifact_id"], doc_id,
                     art["output_hash_sha256"], handoff["normalized_output_type"],
                     handoff["normalized_output_profile"], handoff["adapter_id"],
                     handoff["adapter_version"], handoff["adapter_registry_version"],
                     handoff["policy_snapshot_hash"], "active", supersedes, actor_id, now, now))
                _audit(conn, "intake_promotion", {
                    "promotion_id": promotion_id, "doc_id": doc_id,
                    "source_revision_id": srid, "handoff_id": handoff["handoff_id"],
                    "supersedes_promotion_id": supersedes, "batch_id": batch_id})
        except sqlite3.IntegrityError:
            # Single-winner: a concurrent promote won the partial-unique active slot.
            winner = _active_promotion(conn, srid)
            if winner is not None:
                return {"promoted": False, "idempotent": True,
                        "doc_id": winner["doc_id"], "promotion_id": winner["promotion_id"]}
            raise
        except Exception as exc:
            # Ledger transaction rolled back whole; the indexed doc is already marker-excluded
            # (classify rule), so nothing is exposed; a retry reconciles deterministically.
            logger.exception("promotion ledger transaction failed for %s", srid)
            return {"promoted": False,
                    "reasons": [f"promotion_ledger_failed:{type(exc).__name__}"]}
    finally:
        conn.close()

    trace_recorded = True
    try:
        _persist_trace("promoted", handoff["intake_capability_id"], {
            "promotion_id": promotion_id, "doc_id": doc_id, "source_revision_id": srid})
    except Exception:
        logger.exception("promotion trace emission failed for %s", promotion_id)
        trace_recorded = False
    return {"promoted": True, "doc_id": doc_id, "promotion_id": promotion_id,
            "supersedes_promotion_id": supersedes, "trace_recorded": trace_recorded}


def demote(promotion_id: str, *, actor_id: str = _ACTOR, reason: str | None = None) -> dict:
    """Reversible, provenance-scoped removal of ONE promotion's retrieval rows.
    Intake rows are never touched; scoping comes strictly from the ledger row."""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM intake_promotions WHERE promotion_id = ?",
                           (promotion_id,)).fetchone()
        if row is None:
            return {"demoted": False, "reasons": ["promotion_not_found"]}
        if row["status"] == "demoted":
            return {"demoted": False, "idempotent": True, "doc_id": row["doc_id"]}
        doc_id = row["doc_id"]
        now = utc_now_iso()
        with conn:
            doc = conn.execute("SELECT path FROM docs WHERE doc_id = ?", (doc_id,)).fetchone()
            conn.execute("DELETE FROM doc_chunk_embeddings WHERE chunk_id IN "
                         "(SELECT chunk_id FROM doc_chunks WHERE doc_id = ?)", (doc_id,))
            conn.execute("DELETE FROM doc_chunks_fts WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM doc_chunks WHERE doc_id = ?", (doc_id,))
            if doc is not None:
                conn.execute("DELETE FROM docs_fts WHERE path = ?", (doc["path"],))
            conn.execute("DELETE FROM defs WHERE doc_id = ?", (doc_id,))
            # Defensive, provenance-scoped: promoted docs are never card-wrapped (indexer
            # guard), but remove any card keyed to this doc so demotion can never orphan one.
            conn.execute("DELETE FROM cards WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM docs WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "UPDATE intake_promotions SET status='demoted', demoted_by=?, demoted_at=?, "
                "updated_at=? WHERE promotion_id = ?", (actor_id, now, now, promotion_id))
            _audit(conn, "intake_demotion", {
                "promotion_id": promotion_id, "doc_id": doc_id, "reason": reason,
                "source_revision_id": row["source_revision_id"]})
    finally:
        conn.close()

    # The generated library copy is a derivative; remove it (containment-checked) so a later
    # library scan cannot resurrect the doc. Failure is non-fatal: SQLite is authoritative, and
    # even a resurrected copy re-indexes as marker-excluded (classify rule).
    file_removed = False
    try:
        candidate = _library_root() / PROMOTED_SUBDIR / f"{doc_id}.md"
        if candidate.is_file() and _is_within(candidate, _library_root()):
            candidate.unlink()
            file_removed = True
    except OSError:
        logger.warning("could not remove demoted library copy for %s", doc_id)

    trace_recorded = True
    try:
        _persist_trace("demoted", row["intake_capability_id"], {
            "promotion_id": promotion_id, "doc_id": doc_id, "reason": reason})
    except Exception:
        logger.exception("demotion trace emission failed for %s", promotion_id)
        trace_recorded = False
    return {"demoted": True, "doc_id": doc_id, "promotion_id": promotion_id,
            "library_file_removed": file_removed, "trace_recorded": trace_recorded}


def backfill_handoffs(*, dry_run: bool = True, actor_id: str = _ACTOR) -> dict:
    """Operator-level reconstruction of durable handoff rows for PRE-handoff-era capabilities,
    derived ONLY from durable tables. Per DEC-0003, a re-mint-era capability resolves to the
    earlier era's content-identical artifact row (matched by canonical ref + content hash).
    NO route exposes this; running it against the real boh.db is a separately gated decision.
    """
    conn = db.get_conn()
    planned, skipped = [], []
    try:
        rows = conn.execute(
            "SELECT r.run_id, r.intake_capability_id, r.source_revision_id, "
            "       s.canonical_source_ref, s.source_hash_sha256, "
            "       s.policy_snapshot_hash, s.adapter_registry_version "
            "FROM intake_runs r "
            "JOIN intake_source_revisions s ON s.source_revision_id = r.source_revision_id "
            "WHERE s.lifecycle_state = 'complete' AND r.lifecycle_state = 'complete' "
            "  AND r.intake_capability_id IS NOT NULL "
            "  AND NOT EXISTS (SELECT 1 FROM intake_handoffs h "
            "                  WHERE h.intake_capability_id = r.intake_capability_id)",
        ).fetchall()
        for r in rows:
            cap = conn.execute(
                "SELECT queryable, canon_eligible FROM intake_capabilities "
                "WHERE intake_capability_id = ?", (r["intake_capability_id"],)).fetchone()
            if cap is None or not cap["queryable"] or cap["canon_eligible"]:
                skipped.append({"capability": r["intake_capability_id"],
                                "reason": "capability_missing_or_not_queryable"})
                continue
            # Content-identity artifact resolution (DEC-0003): same canonical ref + same bytes.
            art = None
            for raw in conn.execute(
                    "SELECT raw_artifact_id, source_ref FROM intake_raw_artifacts "
                    "WHERE source_hash_sha256 = ?", (r["source_hash_sha256"],)).fetchall():
                if canonicalize_source_ref(raw["source_ref"]) == r["canonical_source_ref"]:
                    art = conn.execute(
                        "SELECT normalized_artifact_id, output_type, raw_artifact_id "
                        "FROM intake_normalized_artifacts WHERE raw_artifact_id = ?",
                        (raw["raw_artifact_id"],)).fetchone()
                    if art is not None:
                        break
            if art is None:
                skipped.append({"capability": r["intake_capability_id"],
                                "reason": "no_content_identical_normalized_artifact"})
                continue
            adapter = conn.execute(
                "SELECT adapter_id, adapter_version FROM intake_adapter_runs "
                "WHERE raw_artifact_id = ? ORDER BY created_at DESC LIMIT 1",
                (art["raw_artifact_id"],)).fetchone()
            ext = Path(r["canonical_source_ref"]).suffix.lower()
            now = utc_now_iso()
            planned.append({
                "handoff_id": f"ho_backfill_{uuid.uuid4().hex[:16]}",
                "intake_capability_id": r["intake_capability_id"],
                "intake_run_id": r["run_id"],
                "source_revision_id": r["source_revision_id"],
                "normalized_artifact_id": art["normalized_artifact_id"],
                "handoff_ready": 1,
                "handoff_at": now,
                "adapter_id": adapter["adapter_id"] if adapter else "",
                "adapter_version": adapter["adapter_version"] if adapter else "",
                "adapter_registry_version": r["adapter_registry_version"],
                "policy_snapshot_hash": r["policy_snapshot_hash"],
                "normalized_output_type": art["output_type"],
                "normalized_output_profile": ("html_neutralized_markdown"
                                              if ext in (".html", ".htm") else None),
                "warnings_json": json.dumps(["backfilled_handoff"]),
                "created_at": now,
            })
        if not dry_run:
            with conn:
                for row in planned:
                    W._write_handoff_row(conn, row)
                _audit(conn, "intake_handoff_backfill", {
                    "count": len(planned), "skipped": len(skipped)})
    finally:
        conn.close()
    if not dry_run:
        for row in planned:
            _persist_trace("handoff_backfilled", row["intake_capability_id"],
                           {"handoff_id": row["handoff_id"],
                            "source_revision_id": row["source_revision_id"]})
    return {"dry_run": dry_run, "planned": len(planned), "skipped": skipped,
            "handoffs": planned}

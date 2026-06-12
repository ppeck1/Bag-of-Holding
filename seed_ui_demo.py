"""seed_ui_demo.py — Full-UI demo data for Bag of Holding.

Populates the governance / intake / trace / residence tables that the existing
doc-focused seeds (seed_full_demo.py) leave empty, so EVERY /v2 screen has rich,
meaningful data:

  Review Center      — LLM proposals (Proposed Changes), approvals, review-queue patches
  Authority & Audit  — authority resolution log + promotions (Ledger), gate results
                       (Trace & Gates), residence map (Residence)
  Capture & Intake   — intake capabilities (all lifecycle states), quarantine records,
                       duplicate candidates
  Current State      — conflicts surface in the dashboard counts

Idempotent: re-running clears the demo rows it owns (by a `boh-uidemo-` id prefix or
matching marker) and re-inserts. Requires docs to already exist (run seed_full_demo.py
first, or use the auto-seeded library). References real doc_ids from the docs table.

Usage:
    python seed_ui_demo.py            # seed (idempotent)
    python seed_ui_demo.py --clear    # remove demo rows only
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path

REPO = Path(__file__).parent.resolve()
os.environ.setdefault("BOH_DB", str(REPO / "boh.db"))
os.environ.setdefault("BOH_LIBRARY", str(REPO / "library"))
os.environ.setdefault("BOH_DATA_ROOT", str(REPO))

from app.db import connection as db  # noqa: E402

NOW = int(time.time())
DAY = 86400
PFX = "boh-uidemo-"  # ownership marker for idempotent clear


def _iso(ts: int) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


def _doc_ids(limit: int = 30) -> list[dict]:
    return [dict(r) for r in db.fetchall(
        "SELECT doc_id, title, path, authority_state, project FROM docs "
        "ORDER BY updated_ts DESC LIMIT ?", (limit,))]


# Minimal varied doc set so a throwaway/empty DB still drives every screen. Only inserted
# when the docs table is near-empty (a real corpus is left untouched). Owned by the PFX.
_DEMO_DOCS = [
    # (suffix, title, authority_state, project, document_class, canonical_layer, status, age_days, topics)
    ("charter",   "Governance Charter v2",     "canonical",        "Governance", "policy",    "canonical",  "canonical", 3,   "governance charter authority canon"),
    ("viability", "Viability Threshold Note",  "approved",         "Governance", "note",      "supporting", "active",    20,  "viability threshold calibration"),
    ("evidence1", "LOS Evidence Pack",         "reviewed",         "Hospital LOS","evidence",  "evidence",   "active",    45,  "length of stay evidence hospital"),
    ("draft1",    "Draft Intake Doctrine",     "draft",            "Intake",     "note",      "review",     "draft",     2,   "intake doctrine draft pipeline"),
    ("review1",   "Conflict Resolution Memo",  "under_review",     "Governance", "note",      "review",     "review",    9,   "conflict resolution memo contested"),
    ("legacy1",   "Legacy Import Sample",      "non_authoritative","Quarantine / Legacy Import","note","quarantine","legacy", 400, "legacy import quarantine sample"),
    ("canon2",    "Authority Vocabulary Spec", "canonical",        "Governance", "spec",      "canonical",  "canonical", 14,  "authority vocabulary nine labels"),
    ("stale1",    "Aging Calibration Run",     "approved",         "Hospital LOS","note",      "supporting", "active",    200, "calibration aging stale run"),
    ("subj1",     "Interpretation Brief",      "reviewed",         "Governance", "note",      "evidence",   "active",    60,  "interpretation subjective brief"),
    ("conflict1", "Contested Claim A",         "draft",            "E. coli Viability","note", "conflict",   "conflict",  30,  "contested claim viability ecoli"),
    ("conflict2", "Contested Claim B",         "draft",            "E. coli Viability","note", "conflict",   "conflict",  31,  "contested claim viability ecoli"),
    ("primitive-duplicate-a", "Duplicate A",   "draft",            "Primitive Test","note",   "review",     "draft",     5,   "duplicate sample primitive"),
    ("primitive-duplicate-b", "Duplicate B",   "draft",            "Primitive Test","note",   "review",     "draft",     5,   "duplicate sample primitive"),
    ("html-sample","Primitive HTML Fixture",   "non_authoritative","Primitive Test","note",   "quarantine", "quarantined",7,  "html fixture primitive quarantine"),
]


def ensure_demo_docs() -> int:
    """Insert a small varied doc set when the DB is near-empty (throwaway/demo run).
    A real corpus (>= 5 docs) is left untouched. Idempotent (fixed PFX doc_ids)."""
    n0 = db.fetchone("SELECT COUNT(*) AS n FROM docs")
    if n0 and int(dict(n0)["n"]) >= 5:
        return 0
    n = 0
    for suffix, title, auth, project, dclass, layer, status, age, topics in _DEMO_DOCS:
        did = suffix if suffix.startswith("primitive-") or suffix in ("html-sample",) else f"{PFX}doc-{suffix}"
        db.execute(
            """INSERT OR REPLACE INTO docs
               (doc_id, title, path, type, status, authority_state, project, document_class,
                canonical_layer, summary, topics_tokens, updated_ts, epistemic_last_evaluated)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (did, title, f"library/demo/{did}.md", "note", status, auth, project, dclass,
             layer, f"{title} — demo document for full-UI exercise.", topics,
             NOW - age * DAY, _iso(NOW - age * DAY)),
        )
        n += 1
    return n


# ---------------------------------------------------------------------------
# Clear (idempotent)
# ---------------------------------------------------------------------------

def clear_demo() -> None:
    stmts = [
        f"DELETE FROM llm_review_queue WHERE queue_id LIKE '{PFX}%'",
        f"DELETE FROM planar_patch_proposals WHERE patch_id LIKE '{PFX}%'",
        f"DELETE FROM planar_gate_results WHERE gate_result_id LIKE '{PFX}%'",
        f"DELETE FROM authority_promotions WHERE promotion_id LIKE '{PFX}%'",
        f"DELETE FROM authority_resolution_log WHERE metadata_json LIKE '%{PFX}%'",
        f"DELETE FROM planar_information_residence_map WHERE residence_id LIKE '{PFX}%'",
        f"DELETE FROM intake_quarantine_records WHERE quarantine_record_id LIKE '{PFX}%'",
        f"DELETE FROM intake_capabilities WHERE intake_capability_id LIKE '{PFX}%'",
        f"DELETE FROM approval_requests WHERE approval_id LIKE '{PFX}%'",
        f"DELETE FROM conflicts WHERE term LIKE '{PFX}%'",
        f"DELETE FROM lineage WHERE relationship='duplicate_content' AND detail LIKE '%{PFX}%'",
        f"DELETE FROM docs WHERE doc_id LIKE '{PFX}doc-%'",
    ]
    for s in stmts:
        try:
            db.execute(s)
        except Exception as e:
            print(f"  clear skip: {e}")
    print("Cleared prior demo rows.")


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------

def seed_llm_queue(docs: list[dict]) -> int:
    """Review Center → Proposed Changes (status='pending')."""
    samples = [
        ("Tighten the viability threshold from 0.6 to 0.65 per the latest calibration run.", 0.82, "llama3.2"),
        ("Mark this draft as superseded by the v2 governance charter.", 0.71, "llama3.2"),
        ("Add a cross-reference to the conflict-resolution doctrine section.", 0.64, "llama3.2"),
        ("Normalize the authority-state vocabulary to the canonical 9-label set.", 0.78, "llama3.2"),
    ]
    n = 0
    for i, (summary, conf, model) in enumerate(samples):
        d = docs[i % len(docs)]
        qid = f"{PFX}llmq-{i}"
        db.execute(
            """INSERT OR REPLACE INTO llm_review_queue
               (queue_id, doc_id, file_path, queued_ts, status, actor, proposed_json,
                confidence, model, note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (qid, d["doc_id"], d.get("path") or "", NOW - i * 3600, "pending",
             "model", json.dumps({"summary": summary, "doc_id": d["doc_id"]}),
             conf, model, summary),
        )
        n += 1
    return n


def seed_patch_proposals(docs: list[dict]) -> int:
    """Review Center → Review Queue (planar_patch_proposals)."""
    kinds = [
        ("metadata_correction", "Set canonical_layer=evidence (was unassigned).", 2),
        ("lineage_link", "Link as derived_from the v1 source document.", 4),
        ("authority_reclassify", "Reclassify from draft to reviewed after custodian check.", 3),
    ]
    n = 0
    for i, (ptype, change, blast) in enumerate(kinds):
        d = docs[i % len(docs)]
        pid = f"{PFX}patch-{i}"
        db.execute(
            """INSERT OR REPLACE INTO planar_patch_proposals
               (patch_id, proposed_from, proposal_type, proposed_change, evidence_refs_json,
                blast_radius, requires_review_by, status, forbidden_auto_apply, detail_json, created_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, "deterministic_analysis", ptype, change,
             json.dumps([d["doc_id"]]), blast, "custodian", "pending", 1,
             json.dumps({"doc_id": d["doc_id"], "reason": change}), NOW - i * 7200),
        )
        n += 1
    return n


def seed_gate_results(docs: list[dict]) -> int:
    """Authority & Audit → Trace & Gates (planar_gate_results)."""
    rows = [
        ("What is the current viability threshold?", "answer_context", "allowed", []),
        ("Promote the draft charter to canonical.", "canon_mutation", "blocked", ["insufficient_authority", "unreviewed_source"]),
        ("Summarize the conflict between A and B.", "answer_context", "advisory", ["contested_sources"]),
        ("Retrieve evidence for the LOS claim.", "retrieve", "allowed", []),
    ]
    n = 0
    for i, (query, op, posture, blocking) in enumerate(rows):
        d = docs[i % len(docs)]
        gid = f"{PFX}gate-{i}"
        db.execute(
            """INSERT OR REPLACE INTO planar_gate_results
               (gate_result_id, context_pack_id, query, operation, actor_id, mode, posture,
                blocking_reasons_json, warning_reasons_json, required_route, trace_event_type,
                l6_proposal_allowed, created_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (gid, f"{PFX}ctx-{i}", query, op, "local_operator", "exploration", posture,
             json.dumps(blocking), json.dumps([] if posture == "allowed" else ["review_recommended"]),
             "certificate_flow" if posture == "blocked" else "direct", "gate_evaluated",
             1 if posture != "blocked" else 0, NOW - i * 5400),
        )
        n += 1
    return n


def seed_authority_ledger(docs: list[dict]) -> int:
    """Authority & Audit → Authority Ledger (resolution log + promotions)."""
    n = 0
    log_rows = [
        ("approved", "", "governance"),
        ("denied", "actor lacks promotion authority", "custodian"),
        ("approved", "", "reviewer"),
    ]
    for i, (result, fail, role) in enumerate(log_rows):
        d = docs[i % len(docs)]
        db.execute(
            """INSERT INTO authority_resolution_log
               (target_id, target_type, actor_id, actor_role, required_authority,
                authorization_result, failure_reason, timestamp, metadata_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (d["doc_id"], "document", "local_operator", role, "governance",
             result, fail, _iso(NOW - i * 9000),
             json.dumps({"marker": PFX, "note": "demo authority attempt"})),
        )
        n += 1
    promo_rows = [
        ("draft", "reviewed", "custodian review passed"),
        ("reviewed", "approved", "governance sign-off"),
    ]
    for i, (old, new, reason) in enumerate(promo_rows):
        d = docs[i % len(docs)]
        db.execute(
            """INSERT OR REPLACE INTO authority_promotions
               (promotion_id, old_authority, new_authority, promotion_reason, approved_by,
                target_id, target_type, promotion_timestamp, metadata_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (f"{PFX}promo-{i}", old, new, reason, "local_operator",
             d["doc_id"], "document", _iso(NOW - i * 12000), json.dumps({"marker": PFX})),
        )
        n += 1
    return n


def seed_residence(docs: list[dict]) -> int:
    """Authority & Audit → Residence (planar_information_residence_map)."""
    n = 0
    states = ["active", "superseded", "relocated"]
    for i in range(3):
        d = docs[i % len(docs)]
        rid = f"{PFX}res-{i}"
        db.execute(
            """INSERT OR REPLACE INTO planar_information_residence_map
               (residence_id, original_ref, current_ref, current_location, status,
                reason, human_readable_locator, detail_json, created_ts)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (rid, d["doc_id"], d["doc_id"], d.get("path") or f"library/{d['doc_id']}.md",
             states[i], "demo residence record",
             f"Library › {d.get('project') or 'Unassigned'} › {d.get('title') or d['doc_id']}",
             json.dumps({"marker": PFX}), NOW - i * 8000),
        )
        n += 1
    return n


def seed_intake(docs: list[dict]) -> int:
    """Capture & Intake → Capabilities + Quarantine."""
    n = 0
    caps = [
        ("notes/welcome.md", "direct_stage", "accept", "normalized", 1, 1),
        ("imports/legacy.html", "html_neutralize", "hold", "preserved", 1, 0),
        ("imports/report.pdf", "pdf_hold", "hold", "preserved", 0, 0),
        ("imports/archive.zip", "archive_hold", "quarantine", "quarantined", 0, 0),
        ("imports/run.exe", "executable_block", "quarantine", "quarantined", 0, 0),
        ("imports/data.csv", "csv_direct", "accept", "normalized", 1, 1),
    ]
    batch = f"{PFX}batch-001"
    for i, (ref, adapter, lane, lifecycle, normalizable, queryable) in enumerate(caps):
        cid = f"{PFX}cap-{i}"
        db.execute(
            """INSERT OR REPLACE INTO intake_capabilities
               (intake_capability_id, source_ref, batch_id, discovered, preservable,
                normalizable, interpretable, queryable, canon_eligible, required_adapter,
                safety_lane, failure_reason, lifecycle_state, trust_state, authority_default, created_at)
               VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?)""",
            (cid, ref, batch, 1, 1, normalizable, normalizable, queryable, adapter,
             lane, None if lane != "quarantine" else "unsupported_or_unsafe_type",
             lifecycle, "unreviewed_download", "none", _iso(NOW - i * 600)),
        )
        n += 1
        if lane == "quarantine":
            db.execute(
                """INSERT OR REPLACE INTO intake_quarantine_records
                   (quarantine_record_id, intake_capability_id, quarantine_reason,
                    quarantine_category, review_required, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (f"{PFX}qr-{i}", cid,
                 "Unsupported or potentially unsafe file type held for operator review.",
                 "unsafe_type", 1, _iso(NOW - i * 600)),
            )
    return n


def seed_approvals(docs: list[dict]) -> int:
    """Review Center → Approvals (governance approve/pending)."""
    n = 0
    rows = [
        ("canonical_promotion", "draft", "canonical", "Promote demo charter to canon"),
        ("supersede", "active", "superseded", "Supersede v1 with v2"),
    ]
    for i, (action, frm, to, reason) in enumerate(rows):
        d = docs[i % len(docs)]
        db.execute(
            """INSERT OR REPLACE INTO approval_requests
               (approval_id, action_type, doc_id, from_state, to_state, requested_by,
                requested_ts, reason, status, impact_summary)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (f"{PFX}apr-{i}", action, d["doc_id"], frm, to, "local_operator",
             NOW - i * 4000, reason, "pending",
             json.dumps({"required_authority": "governance", "marker": PFX})),
        )
        n += 1
    return n


def seed_duplicate_conflicts(docs: list[dict]) -> int:
    """Capture & Intake → Duplicates. /api/duplicates reads lineage rows with
    relationship='duplicate_content'."""
    n = 0
    # Prefer the known primitive duplicate pair; else fall back to the first two docs.
    by_id = {d["doc_id"]: d for d in docs}
    pairs = []
    if "primitive-duplicate-a" in by_id and "primitive-duplicate-b" in by_id:
        pairs.append(("primitive-duplicate-a", "primitive-duplicate-b"))
    if len(docs) >= 4:
        pairs.append((docs[2]["doc_id"], docs[3]["doc_id"]))
    for i, (a, b) in enumerate(pairs):
        # Clear any prior demo duplicate lineage for this pair, then insert.
        db.execute(
            "DELETE FROM lineage WHERE relationship='duplicate_content' AND doc_id=? AND related_doc_id=?",
            (a, b),
        )
        db.execute(
            """INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail)
               VALUES (?,?,?,?,?)""",
            (a, b, "duplicate_content", NOW - i * 3000,
             json.dumps({"marker": PFX, "similarity": 0.97})),
        )
        n += 1
    return n


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Seed full-UI demo data.")
    p.add_argument("--clear", action="store_true", help="Remove demo rows only.")
    args = p.parse_args()

    db.init_db()
    # Ensure lazily-created tables exist (a throwaway DB only has what init_db builds).
    try:
        from app.core.llm_queue import _ensure_table as _ensure_llm_queue
        _ensure_llm_queue()
    except Exception as e:
        print(f"  note: could not ensure llm_review_queue: {e}")

    clear_demo()
    if args.clear:
        print("Done (clear only).")
        return

    made = ensure_demo_docs()
    if made:
        print(f"Inserted {made} demo docs (DB was near-empty).")
    docs = _doc_ids(30)
    if not docs:
        print("ERROR: no docs in DB after ensure_demo_docs(). Aborting.")
        raise SystemExit(1)

    counts = {
        "llm_review_queue": seed_llm_queue(docs),
        "patch_proposals": seed_patch_proposals(docs),
        "gate_results": seed_gate_results(docs),
        "authority_ledger": seed_authority_ledger(docs),
        "residence_map": seed_residence(docs),
        "intake_capabilities": seed_intake(docs),
        "approval_requests": seed_approvals(docs),
        "duplicate_conflicts": seed_duplicate_conflicts(docs),
    }
    print("Seeded full-UI demo data:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"Docs referenced: {len(docs)}")
    print("Every /v2 screen now has data. Open http://127.0.0.1:8000/")


if __name__ == "__main__":
    main()

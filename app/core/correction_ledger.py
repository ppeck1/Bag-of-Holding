"""Audited correction ledger for Planar Gate behavior.

The ledger records proposed corrections and approved correction records. It
does not apply rule, canon, schema, source-trust, or routing mutations.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from app.db import connection as db
from app.core.plane_card import log_storage_event


VALID_PATCH_STATUSES = {"proposed", "approved", "rejected", "deferred", "superseded"}
VALID_PROPOSAL_TYPES = {
    "retrieval_route_patch",
    "rct_expected_plane_patch",
    "gate_rule_patch",
    "fixture_case_patch",
    "schema_patch",
    "scalar_threshold_patch",
    "dominance_policy_patch",
    "source_trust_patch",
}
VALID_BLAST_RADIUS = {"local", "domain", "global"}
VALID_REVIEWERS = {"reviewer", "schema_owner", "authority_owner", "domain_owner"}
VALID_RESIDENCE_LOCATIONS = {
    "PlaneCard",
    "SourceVersion",
    "ContextPack",
    "GateRule",
    "FixtureCase",
    "TraceEvent",
    "CanonChangeRecord",
    "PatchProposal",
}
VALID_RESIDENCE_STATUSES = {"active", "superseded", "deprecated", "quarantined", "merged", "split"}


def _json(value: Any, default: Any) -> str:
    return json.dumps(value if value is not None else default, sort_keys=True)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _now() -> int:
    return int(time.time())


def _id(prefix: str, *parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return prefix + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def _row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    out = dict(row)
    for key in (
        "blocking_reasons_json",
        "warning_reasons_json",
        "allowed_context_refs_json",
        "withheld_context_refs_json",
        "l6_proposal_types_json",
        "impacted_refs_json",
        "evidence_refs_json",
        "changed_objects_json",
        "old_location_refs_json",
        "new_location_refs_json",
        "supersedes_refs_json",
        "regression_fixture_refs_json",
    ):
        if key in out:
            out[key[:-5]] = _loads(out[key], [])
    for key in (
        "context_allowed_basis_json",
        "context_pack_json",
        "gate_result_json",
        "detail_json",
        "fixture_json",
        "expected_gate_result_json",
    ):
        if key in out:
            out[key[:-5]] = _loads(out[key], {})
    return out


def record_gate_result(context_pack: dict[str, Any], gate_result: dict[str, Any]) -> dict[str, Any]:
    gate_result_id = gate_result.get("gate_result_id") or _id(
        "gate_", context_pack.get("context_pack_id"), gate_result.get("posture")
    )
    created_ts = int(gate_result.get("created_ts") or _now())
    db.execute(
        """INSERT OR REPLACE INTO planar_gate_results
           (gate_result_id, context_pack_id, query, operation, actor_id, mode, posture,
            blocking_reasons_json, warning_reasons_json, allowed_context_refs_json,
            withheld_context_refs_json, required_route, trace_event_type,
            l6_proposal_allowed, l6_proposal_types_json, context_allowed_basis_json,
            context_pack_json, gate_result_json, created_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            gate_result_id,
            context_pack.get("context_pack_id"),
            context_pack.get("query") or "",
            context_pack.get("operation") or "answer_context",
            context_pack.get("actor_id") or "",
            context_pack.get("mode") or "",
            gate_result.get("posture"),
            _json(gate_result.get("blocking_reasons"), []),
            _json(gate_result.get("warning_reasons"), []),
            _json(gate_result.get("allowed_context_refs"), []),
            _json(gate_result.get("withheld_context_refs"), []),
            gate_result.get("required_route"),
            gate_result.get("trace_event_type") or "gate_passed",
            1 if gate_result.get("l6_proposal_allowed") else 0,
            _json(gate_result.get("l6_proposal_types"), []),
            _json(gate_result.get("context_allowed_basis"), {}),
            _json(context_pack, {}),
            _json(gate_result, {}),
            created_ts,
        ),
    )
    event_id = log_storage_event(
        "planar_gate_result_recorded",
        subject_type="planar_gate_result",
        subject_id=gate_result_id,
        actor_id=context_pack.get("actor_id"),
        detail={"context_pack_id": context_pack.get("context_pack_id"), "posture": gate_result.get("posture")},
    )
    stored = get_gate_result(gate_result_id) or {}
    stored["storage_event_id"] = event_id
    return stored


def get_gate_result(gate_result_id: str) -> dict[str, Any] | None:
    return _row(db.fetchone("SELECT * FROM planar_gate_results WHERE gate_result_id = ?", (gate_result_id,)))


def list_gate_results(limit: int = 50, posture: str | None = None) -> list[dict[str, Any]]:
    if posture:
        rows = db.fetchall(
            "SELECT * FROM planar_gate_results WHERE posture = ? ORDER BY created_ts DESC LIMIT ?",
            (posture, limit),
        )
    else:
        rows = db.fetchall("SELECT * FROM planar_gate_results ORDER BY created_ts DESC LIMIT ?", (limit,))
    return [_row(r) for r in rows]


def record_mistake_event(
    *,
    detected_from: str,
    operation: str,
    context_pack_ref: str,
    mistake_class: str,
    actor_ref: str = "",
    query_ref: str | None = None,
    expected_gate_result_ref: str | None = None,
    actual_gate_result_ref: str | None = None,
    impacted_refs: list[str] | None = None,
    severity: str = "medium",
    trace_event_ref: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mistake_id = _id(
        "mistake_", detected_from, operation, context_pack_ref, mistake_class, impacted_refs or [], detail or {}
    )
    db.execute(
        """INSERT OR REPLACE INTO planar_mistake_events
           (mistake_id, detected_from, operation, actor_ref, query_ref, context_pack_ref,
            expected_gate_result_ref, actual_gate_result_ref, mistake_class,
            impacted_refs_json, severity, trace_event_ref, detail_json, created_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            mistake_id,
            detected_from,
            operation,
            actor_ref,
            query_ref,
            context_pack_ref,
            expected_gate_result_ref,
            actual_gate_result_ref,
            mistake_class,
            _json(impacted_refs or [], []),
            severity,
            trace_event_ref,
            _json(detail or {}, {}),
            _now(),
        ),
    )
    event_id = log_storage_event(
        "mistake_event_recorded",
        subject_type="planar_mistake_event",
        subject_id=mistake_id,
        actor_id=actor_ref,
        detail={"mistake_class": mistake_class, "severity": severity},
    )
    stored = get_mistake_event(mistake_id) or {}
    stored["storage_event_id"] = event_id
    return stored


def get_mistake_event(mistake_id: str) -> dict[str, Any] | None:
    return _row(db.fetchone("SELECT * FROM planar_mistake_events WHERE mistake_id = ?", (mistake_id,)))


def create_patch_proposal(
    *,
    proposed_from: str,
    proposal_type: str,
    proposed_change: str,
    evidence_refs: list[str] | None = None,
    blast_radius: str = "local",
    requires_review_by: str = "reviewer",
    detail: dict[str, Any] | None = None,
    forbidden_auto_apply: bool | None = None,
) -> dict[str, Any]:
    if proposal_type not in VALID_PROPOSAL_TYPES:
        raise ValueError(f"invalid proposal_type: {proposal_type}")
    if blast_radius not in VALID_BLAST_RADIUS:
        raise ValueError(f"invalid blast_radius: {blast_radius}")
    if requires_review_by not in VALID_REVIEWERS:
        raise ValueError(f"invalid requires_review_by: {requires_review_by}")
    patch_id = _id("patch_", proposed_from, proposal_type, proposed_change, evidence_refs or [])
    db.execute(
        """INSERT OR REPLACE INTO planar_patch_proposals
           (patch_id, proposed_from, proposal_type, proposed_change, evidence_refs_json,
            blast_radius, requires_review_by, status, forbidden_auto_apply, detail_json, created_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            patch_id,
            proposed_from,
            proposal_type,
            proposed_change,
            _json(evidence_refs or [], []),
            blast_radius,
            requires_review_by,
            "proposed",
            1,
            _json(detail or {}, {}),
            _now(),
        ),
    )
    event_id = log_storage_event(
        "patch_proposal_created",
        subject_type="planar_patch_proposal",
        subject_id=patch_id,
        detail={"proposed_from": proposed_from, "proposal_type": proposal_type, "forbidden_auto_apply": True},
    )
    stored = get_patch_proposal(patch_id) or {}
    stored["storage_event_id"] = event_id
    return stored


def get_patch_proposal(patch_id: str) -> dict[str, Any] | None:
    return _row(db.fetchone("SELECT * FROM planar_patch_proposals WHERE patch_id = ?", (patch_id,)))


def list_patch_proposals(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    if status:
        rows = db.fetchall(
            "SELECT * FROM planar_patch_proposals WHERE status = ? ORDER BY created_ts DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = db.fetchall("SELECT * FROM planar_patch_proposals ORDER BY created_ts DESC LIMIT ?", (limit,))
    return [_row(r) for r in rows]


def reject_patch_proposal(patch_id: str, *, reviewed_by: str, review_note: str = "") -> dict[str, Any]:
    existing = get_patch_proposal(patch_id)
    if not existing:
        return {"success": False, "error": "patch_proposal_not_found"}
    ts = _now()
    db.execute(
        """UPDATE planar_patch_proposals
           SET status = 'rejected', reviewed_by = ?, reviewed_at = ?, review_note = ?
           WHERE patch_id = ?""",
        (reviewed_by, ts, review_note, patch_id),
    )
    event_id = log_storage_event(
        "patch_proposal_rejected",
        subject_type="planar_patch_proposal",
        subject_id=patch_id,
        actor_id=reviewed_by,
        detail={"review_note": review_note},
    )
    stored = get_patch_proposal(patch_id) or {}
    stored["success"] = True
    stored["storage_event_id"] = event_id
    return stored


def approve_patch_proposal(
    patch_id: str,
    *,
    approved_by: str,
    changed_objects: list[str],
    old_location_refs: list[str] | None = None,
    new_location_refs: list[str] | None = None,
    supersedes_refs: list[str] | None = None,
    migration_note: str,
    regression_fixture_refs: list[str] | None = None,
    trace_event_ref: str | None = None,
    residence_updates: list[dict[str, Any]] | None = None,
    review_note: str = "",
) -> dict[str, Any]:
    proposal = get_patch_proposal(patch_id)
    if not proposal:
        return {"success": False, "error": "patch_proposal_not_found"}
    regression_fixture_refs = regression_fixture_refs or []
    if not regression_fixture_refs and proposal.get("proposal_type") != "schema_patch":
        return {"success": False, "error": "regression_fixture_refs_required"}
    new_location_refs = new_location_refs or []
    ts = _now()
    canon_change_id = _id("canon_change_", patch_id, approved_by, changed_objects, new_location_refs, ts)
    conn = db.get_conn()
    try:
        conn.execute(
            """UPDATE planar_patch_proposals
               SET status = 'approved', reviewed_by = ?, reviewed_at = ?, review_note = ?,
                   forbidden_auto_apply = 1
               WHERE patch_id = ?""",
            (approved_by, ts, review_note, patch_id),
        )
        conn.execute(
            """INSERT INTO planar_canon_change_records
               (canon_change_id, patch_proposal_ref, approved_by, approved_at,
                changed_objects_json, old_location_refs_json, new_location_refs_json,
                supersedes_refs_json, migration_note, regression_fixture_refs_json,
                trace_event_ref, created_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                canon_change_id,
                patch_id,
                approved_by,
                ts,
                _json(changed_objects, []),
                _json(old_location_refs or [], []),
                _json(new_location_refs, []),
                _json(supersedes_refs or [], []),
                migration_note,
                _json(regression_fixture_refs, []),
                trace_event_ref,
                ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    event_id = log_storage_event(
        "patch_proposal_approved",
        subject_type="planar_patch_proposal",
        subject_id=patch_id,
        actor_id=approved_by,
        detail={"canon_change_id": canon_change_id, "regression_fixture_refs": regression_fixture_refs},
    )
    log_storage_event(
        "canon_change_recorded",
        subject_type="planar_canon_change_record",
        subject_id=canon_change_id,
        actor_id=approved_by,
        detail={"patch_id": patch_id, "changed_objects": changed_objects},
    )
    residences = []
    for update in residence_updates or []:
        residences.append(upsert_information_residence(**update))
    return {
        "success": True,
        "patch_proposal": get_patch_proposal(patch_id),
        "canon_change_record": get_canon_change_record(canon_change_id),
        "residence_updates": residences,
        "storage_event_id": event_id,
    }


def get_canon_change_record(canon_change_id: str) -> dict[str, Any] | None:
    return _row(db.fetchone("SELECT * FROM planar_canon_change_records WHERE canon_change_id = ?", (canon_change_id,)))


def list_canon_change_records(limit: int = 50) -> list[dict[str, Any]]:
    rows = db.fetchall("SELECT * FROM planar_canon_change_records ORDER BY created_ts DESC LIMIT ?", (limit,))
    return [_row(r) for r in rows]


def upsert_information_residence(
    *,
    original_ref: str,
    current_ref: str,
    current_location: str,
    status: str,
    reason: str,
    human_readable_locator: str,
    moved_by_event_ref: str | None = None,
    superseded_by: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if current_location not in VALID_RESIDENCE_LOCATIONS:
        raise ValueError(f"invalid current_location: {current_location}")
    if status not in VALID_RESIDENCE_STATUSES:
        raise ValueError(f"invalid status: {status}")
    residence_id = _id("residence_", original_ref, current_ref, current_location)
    db.execute(
        """INSERT OR REPLACE INTO planar_information_residence_map
           (residence_id, original_ref, current_ref, current_location, status,
            moved_by_event_ref, superseded_by, reason, human_readable_locator,
            detail_json, created_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            residence_id,
            original_ref,
            current_ref,
            current_location,
            status,
            moved_by_event_ref,
            superseded_by,
            reason,
            human_readable_locator,
            _json(detail or {}, {}),
            _now(),
        ),
    )
    event_id = log_storage_event(
        "information_residence_updated",
        subject_type="planar_information_residence",
        subject_id=residence_id,
        detail={"original_ref": original_ref, "current_ref": current_ref, "status": status},
    )
    stored = get_information_residence(original_ref) or {}
    stored["storage_event_id"] = event_id
    return stored


def get_information_residence(original_ref: str) -> dict[str, Any] | None:
    return _row(
        db.fetchone(
            "SELECT * FROM planar_information_residence_map WHERE original_ref = ? ORDER BY created_ts DESC LIMIT 1",
            (original_ref,),
        )
    )


def list_information_residence(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    if status:
        rows = db.fetchall(
            "SELECT * FROM planar_information_residence_map WHERE status = ? ORDER BY created_ts DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = db.fetchall("SELECT * FROM planar_information_residence_map ORDER BY created_ts DESC LIMIT ?", (limit,))
    return [_row(r) for r in rows]


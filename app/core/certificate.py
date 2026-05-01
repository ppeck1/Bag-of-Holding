"""app/core/certificate.py: Certificate Gate for Bag of Holding v2.

Phase 20: Canonical mutation requires a valid certificate.

Mutation path (the only legal path):
  request_certificate() → review → approve_certificate() → apply_transition()

There is no shortcut. No bypass. No admin exception.

Certificate invariants:
  - issuer_type must be "human"
  - evidence_refs must be non-empty
  - reason must be non-empty
  - q/c must meet risk-class thresholds
  - valid_until must be a future date at request time
  - certificate must be in 'approved' status before any transition applies
  - reversion also requires a certificate (no silent rollback)

History is immutable. Certificates are never deleted.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from app.db import connection as db
from app.core.plane_interface import create_interface
from app.core.constraint_lattice import (
    check_transition_legal, get_risk_class, get_qc_thresholds,
    log_lattice_event, QC_THRESHOLDS,
    VALID_AUTHORITY_PLANES, validate_authority_plane, normalize_authority_plane,
)

# ── ID generation ──────────────────────────────────────────────────────────────

def _new_cert_id() -> str:
    uid = uuid.uuid4().hex[:10].upper()
    return f"CERT_{uid}"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ── Dataclass ──────────────────────────────────────────────────────────────────

@dataclass
class Certificate:
    certificate_id:   str
    node_id:          str
    from_d:           int | None
    to_d:             int
    from_mode:        str | None
    to_mode:          str | None
    reason:           str
    evidence_refs:    list[str]
    issuer_type:      str        # must be "human"
    review_required:  bool
    risk_class:       str
    cost_of_wrong:    str | None
    q:                float
    c:                float
    valid_until:      str
    context_ref:      str | None
    created_at:       str
    status:           str        # pending / approved / rejected / revoked / expired
    reviewed_at:      str | None = None
    reviewed_by:      str | None = None
    review_note:      str | None = None
    authority_plane:  str        = "verification"
    plane_authority:  str        = "verification"  # legacy alias; not authoritative

    def to_dict(self) -> dict:
        return asdict(self)


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_certificate_request(
    node_id:       str,
    from_d:        int | None,
    to_d:          int,
    reason:        str,
    evidence_refs: list[str],
    issuer_type:   str,
    q:             float,
    c:             float,
    valid_until:   str,
    authority_plane: str = "verification",
    **kwargs,
) -> dict[str, Any]:
    """Validate a certificate request against all invariants.

    Returns {valid: bool, errors: list[str], risk_class: str}.
    """
    errors: list[str] = []

    # node_id required
    if not node_id or not node_id.strip():
        errors.append("node_id is required")

    # Transition must be defined and non-identity
    if to_d is None:
        errors.append("to_d is required (target d-state)")
    elif from_d == to_d:
        errors.append(
            f"from_d == to_d == {from_d}: identity transition — no certificate needed"
        )

    # reason required
    if not reason or not reason.strip():
        errors.append("reason is required and must be non-empty")

    # evidence_refs must be non-empty
    if not evidence_refs:
        errors.append("evidence_refs must be non-empty — cite at least one source")

    # authority_plane is mandatory, epistemic, and explicit
    for err in validate_authority_plane(authority_plane):
        errors.append(err)

    # issuer_type must be human
    if issuer_type not in {"human"}:
        errors.append(
            f"issuer_type must be 'human'. Got {issuer_type!r}. "
            f"LLM, projection, and automated issuers are not permitted."
        )

    # q/c thresholds
    risk_class = get_risk_class(from_d, to_d)
    thresholds = get_qc_thresholds(risk_class)
    if q < thresholds["min_q"]:
        errors.append(
            f"q={q:.2f} below {risk_class}-risk threshold (min_q={thresholds['min_q']})"
        )
    if c < thresholds["min_c"]:
        errors.append(
            f"c={c:.2f} below {risk_class}-risk threshold (min_c={thresholds['min_c']})"
        )

    # valid_until must be parseable and in the future at request time
    if not valid_until:
        errors.append("valid_until is required")
    else:
        try:
            exp = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(tz=timezone.utc):
                errors.append(
                    f"valid_until={valid_until!r} is in the past — "
                    f"expired certificates cannot be requested"
                )
        except Exception:
            errors.append(f"valid_until={valid_until!r} is not a valid ISO timestamp")

    return {"valid": len(errors) == 0, "errors": errors, "risk_class": risk_class}


# ── Certificate CRUD ───────────────────────────────────────────────────────────

def request_certificate(
    node_id:       str,
    from_d:        int | None,
    to_d:          int,
    reason:        str,
    evidence_refs: list[str],
    issuer_type:   str = "human",
    q:             float = 0.0,
    c:             float = 0.0,
    valid_until:   str  = "",
    from_mode:     str | None = None,
    to_mode:       str | None = None,
    cost_of_wrong: str | None = None,
    context_ref:   str | None = None,
    authority_plane: str = "verification",
    plane_authority: str | None = None,
) -> dict[str, Any]:
    """Request a new certificate for a d-state transition.

    Returns {ok, certificate_id, errors, validation}.
    All requests are validated before being persisted.
    Only 'human' issuers are accepted.
    """
    validation = validate_certificate_request(
        node_id=node_id, from_d=from_d, to_d=to_d,
        reason=reason, evidence_refs=evidence_refs,
        issuer_type=issuer_type, q=q, c=c, valid_until=valid_until,
        authority_plane=authority_plane,
    )
    if not validation["valid"]:
        return {"ok": False, "errors": validation["errors"], "certificate_id": None}

    authority_plane = normalize_authority_plane(authority_plane)
    legacy_plane = normalize_authority_plane(plane_authority) or authority_plane
    risk_class    = validation["risk_class"]
    review_needed = risk_class in {"high", "critical"} or from_d == 0
    cert_id       = _new_cert_id()
    now           = _now_iso()

    db.execute(
        """
        INSERT INTO certificates
          (certificate_id, node_id, from_d, to_d, from_mode, to_mode,
           reason, evidence_refs_json, issuer_type, review_required,
           risk_class, cost_of_wrong, q, c, valid_until, context_ref,
           created_at, status, authority_plane, plane_authority)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            cert_id, node_id, from_d, to_d, from_mode, to_mode,
            reason, json.dumps(evidence_refs), issuer_type,
            int(review_needed), risk_class, cost_of_wrong,
            q, c, valid_until, context_ref, now, "pending", authority_plane, legacy_plane,
        ),
    )

    log_lattice_event(
        event_type     = "certificate_requested",
        node_id        = node_id,
        from_d         = from_d,
        to_d           = to_d,
        from_mode      = from_mode,
        to_mode        = to_mode,
        reason         = reason,
        certificate_id = cert_id,
        severity       = "info",
        detail         = {"risk_class": risk_class, "review_required": review_needed, "authority_plane": authority_plane},
    )

    return {
        "ok":              True,
        "certificate_id":  cert_id,
        "errors":          [],
        "risk_class":      risk_class,
        "review_required": review_needed,
        "status":          "pending",
        "authority_plane": authority_plane,
    }


def approve_certificate(
    certificate_id: str,
    reviewed_by:    str,
    review_note:    str = "",
) -> dict[str, Any]:
    """Approve a pending certificate.

    Approval does NOT automatically apply the transition — it only changes
    the certificate status to 'approved'. A separate apply_transition()
    call must be made, which checks the lattice rules again.
    """
    cert = get_certificate(certificate_id)
    if not cert:
        return {"ok": False, "error": f"Certificate {certificate_id!r} not found"}
    if cert["status"] != "pending":
        return {"ok": False, "error": f"Certificate status is {cert['status']!r} — only pending certificates can be approved"}
    if not reviewed_by or not reviewed_by.strip():
        return {"ok": False, "error": "reviewed_by is required for approval"}

    now = _now_iso()
    db.execute(
        "UPDATE certificates SET status=?, reviewed_at=?, reviewed_by=?, review_note=? WHERE certificate_id=?",
        ("approved", now, reviewed_by, review_note, certificate_id),
    )
    log_lattice_event(
        event_type     = "certificate_approved",
        node_id        = cert["node_id"],
        from_d         = cert["from_d"],
        to_d           = cert["to_d"],
        certificate_id = certificate_id,
        severity       = "info",
        detail         = {"reviewed_by": reviewed_by},
    )
    return {"ok": True, "certificate_id": certificate_id, "status": "approved"}


def reject_certificate(
    certificate_id: str,
    reviewed_by:    str,
    review_note:    str = "",
) -> dict[str, Any]:
    """Reject a pending certificate."""
    cert = get_certificate(certificate_id)
    if not cert:
        return {"ok": False, "error": f"Certificate {certificate_id!r} not found"}
    if cert["status"] != "pending":
        return {"ok": False, "error": f"Certificate status is {cert['status']!r}"}

    now = _now_iso()
    db.execute(
        "UPDATE certificates SET status=?, reviewed_at=?, reviewed_by=?, review_note=? WHERE certificate_id=?",
        ("rejected", now, reviewed_by, review_note, certificate_id),
    )
    log_lattice_event(
        event_type     = "certificate_rejected",
        node_id        = cert["node_id"],
        from_d         = cert["from_d"],
        to_d           = cert["to_d"],
        certificate_id = certificate_id,
        severity       = "info",
        detail         = {"reviewed_by": reviewed_by, "note": review_note},
    )
    return {"ok": True, "certificate_id": certificate_id, "status": "rejected"}


def revoke_certificate(
    certificate_id: str,
    revoked_by:     str,
    reason:         str = "",
) -> dict[str, Any]:
    """Revoke an approved certificate (e.g. evidence was found to be unreliable)."""
    cert = get_certificate(certificate_id)
    if not cert:
        return {"ok": False, "error": f"Certificate {certificate_id!r} not found"}
    if cert["status"] not in {"approved", "pending"}:
        return {"ok": False, "error": f"Certificate status is {cert['status']!r} — cannot revoke"}

    db.execute(
        "UPDATE certificates SET status='revoked', review_note=? WHERE certificate_id=?",
        (reason, certificate_id),
    )
    log_lattice_event(
        event_type     = "certificate_revoked",
        node_id        = cert["node_id"],
        from_d         = cert["from_d"],
        to_d           = cert["to_d"],
        certificate_id = certificate_id,
        severity       = "warning",
        detail         = {"revoked_by": revoked_by, "reason": reason},
    )
    return {"ok": True, "certificate_id": certificate_id, "status": "revoked"}


# ── Retrieval ──────────────────────────────────────────────────────────────────

def _row_to_cert(row: dict) -> dict:
    d = dict(row)
    try:
        d["evidence_refs"] = json.loads(d.get("evidence_refs_json") or "[]")
    except Exception:
        d["evidence_refs"] = []
    d["review_required"] = bool(d.get("review_required"))
    d["authority_plane"] = normalize_authority_plane(d.get("authority_plane") or d.get("plane_authority") or "verification")
    return d


def get_certificate(certificate_id: str) -> dict | None:
    row = db.fetchone("SELECT * FROM certificates WHERE certificate_id = ?", (certificate_id,))
    return _row_to_cert(dict(row)) if row else None


def get_approved_certificate_for_node(node_id: str, to_d: int) -> dict | None:
    """Return the most recent approved, non-expired certificate for a transition."""
    rows = db.fetchall(
        """SELECT * FROM certificates
           WHERE node_id = ? AND to_d = ? AND status = 'approved'
             AND valid_until >= date('now')
           ORDER BY created_at DESC LIMIT 1""",
        (node_id, to_d),
    )
    return _row_to_cert(dict(rows[0])) if rows else None


def get_pending_certificates(limit: int = 100) -> list[dict]:
    rows = db.fetchall(
        "SELECT * FROM certificates WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return [_row_to_cert(dict(r)) for r in rows]


def get_certificate_history(node_id: str) -> list[dict]:
    """Return all certificates for a node, newest first. Immutable — no deletes."""
    rows = db.fetchall(
        "SELECT * FROM certificates WHERE node_id = ? ORDER BY created_at DESC",
        (node_id,),
    )
    return [_row_to_cert(dict(r)) for r in rows]


# ── Reversion (also requires certificate) ─────────────────────────────────────

def request_reversion_certificate(
    node_id:       str,
    from_d:        int,
    reason:        str,
    evidence_refs: list[str],
    q:             float,
    c:             float,
    valid_until:   str,
    reviewed_by:   str,
    context_ref:   str | None = None,
) -> dict[str, Any]:
    """Canonical → review → revert path. Reversion also requires a certificate.
    No silent rollback. History remains visible.

    This creates a certificate for d=from_d → d=0 (reversion to contain).
    The reversion must be human-initiated and explicitly reviewed.
    """
    result = request_certificate(
        node_id        = node_id,
        from_d         = from_d,
        to_d           = 0,
        from_mode      = None,
        to_mode        = "contain",
        reason         = f"REVERSION: {reason}",
        evidence_refs  = evidence_refs,
        issuer_type    = "human",
        q              = q,
        c              = c,
        valid_until    = valid_until,
        context_ref    = context_ref,
        authority_plane= "governance",
        cost_of_wrong  = "Reversion may discard canonical knowledge",
    )
    if not result["ok"]:
        return result

    log_lattice_event(
        event_type     = "reversion_requested",
        node_id        = node_id,
        from_d         = from_d,
        to_d           = 0,
        reason         = reason,
        certificate_id = result["certificate_id"],
        severity       = "warning",
        detail         = {"canonical_reversion": True, "reviewed_by": reviewed_by},
    )
    return result


# ── Phase 20.1 canonical mutation door ───────────────────────────────────────

def apply_canonical_promotion(node_id: str, certificate_id: str) -> dict[str, Any]:
    """The only legal canonical promotion entry point.

    Requires an approved, non-expired certificate whose authority_plane is valid
    and aligned with the transition. Writes immutable certificate lineage onto
    the canonical node. No admin/dev/demo bypass exists here.
    """
    if not node_id or not certificate_id:
        return {"ok": False, "error": "node_id and certificate_id are required"}

    cert = get_certificate(certificate_id)
    if not cert:
        return {"ok": False, "error": f"Certificate {certificate_id!r} not found"}
    if cert.get("node_id") != node_id:
        return {"ok": False, "error": "certificate node_id mismatch"}

    doc = db.fetchone("SELECT * FROM docs WHERE doc_id=?", (node_id,))
    if not doc:
        return {"ok": False, "error": f"Document {node_id!r} not found"}
    doc = dict(doc)

    to_d = cert.get("to_d")
    verdict = check_transition_legal(
        from_d=doc.get("epistemic_d"),
        to_d=to_d,
        from_mode=doc.get("epistemic_m"),
        to_mode=cert.get("to_mode"),
        certificate=cert,
    )
    if not verdict.get("legal"):
        return {"ok": False, "error": verdict.get("reason"), "errors": verdict.get("errors", []), "verdict": verdict}

    source_plane = (doc.get("canonical_layer") or doc.get("status") or "internal").lower()
    if source_plane == "supporting":
        source_plane = "internal"
    if source_plane not in {"evidence", "internal", "review", "verification", "governance", "canonical", "conflict", "archive", "quarantine"}:
        source_plane = "internal"
    interface_result = create_interface(
        source_plane=source_plane,
        target_plane="canonical",
        translation_reason="approved certificate permits canonical promotion",
        loss_notes=[
            "source-plane context compressed into canonical state",
            "supporting evidence retained by certificate reference",
        ],
        certificate_refs=[certificate_id],
        q_delta=0.0,
        c_delta=0.0,
        authority_plane=cert.get("authority_plane") or "governance",
        node_id=node_id,
        created_by=cert.get("reviewed_by") or "human",
        metadata={"phase": "21", "promotion_path": "certificate_to_interface_to_canonical"},
    )
    if not interface_result.get("ok"):
        return {"ok": False, "error": "plane interface creation failed", "errors": interface_result.get("errors", [])}
    interface_id = interface_result["interface_id"]

    now_ts = int(time.time())
    db.execute(
        """UPDATE docs
           SET status='canonical', canonical_layer='canonical', authority_state='canonical',
               operator_state='release', operator_intent='canonize',
               epistemic_d=?, epistemic_m=COALESCE(?, epistemic_m),
               promoted_by_certificate=?, updated_ts=?
           WHERE doc_id=?""",
        (to_d, cert.get("to_mode"), certificate_id, now_ts, node_id),
    )
    log_lattice_event(
        event_type="canonical_promotion_applied",
        node_id=node_id,
        from_d=doc.get("epistemic_d"),
        to_d=to_d,
        from_mode=doc.get("epistemic_m"),
        to_mode=cert.get("to_mode"),
        reason="Canonical promotion applied through approved certificate",
        certificate_id=certificate_id,
        severity="info",
        detail={"authority_plane": cert.get("authority_plane"), "interface_id": interface_id},
    )
    return {"ok": True, "node_id": node_id, "certificate_id": certificate_id, "interface_id": interface_id, "status": "canonical"}

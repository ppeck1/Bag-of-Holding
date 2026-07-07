"""app/core/plane_interface.py: Cross-plane interface artifacts for BOH v2.

Phase 21 — Plane Interfaces.

Invariant:
    Plane A must not directly mutate Plane B.
    Cross-plane movement is legal only through an explicit Interface artifact.

Interfaces are audit objects, not convenience metadata. They record why a
translation occurred, which certificate authorized it, what semantic loss was
accepted, and how epistemic quality/confidence changed during the move.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any

from app.db import connection as db
from app.core.constraint_lattice import normalize_authority_plane, validate_authority_plane

VALID_PLANES = {
    "evidence",
    "internal",
    "review",
    "verification",
    "governance",
    "canonical",
    "conflict",
    "archive",
    "quarantine",
}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _new_interface_id() -> str:
    return f"I_{uuid.uuid4().hex[:10].upper()}"


def normalize_plane(value: str | None) -> str:
    return (value or "").strip().lower()


def validate_plane(value: str | None, field_name: str) -> list[str]:
    plane = normalize_plane(value)
    if not plane:
        return [f"{field_name} is required"]
    if plane not in VALID_PLANES:
        return [f"invalid {field_name} {plane!r}; expected one of {sorted(VALID_PLANES)}"]
    return []


@dataclass
class PlaneInterface:
    interface_id: str
    source_plane: str
    target_plane: str
    translation_reason: str
    loss_notes: list[str] = field(default_factory=list)
    certificate_refs: list[str] = field(default_factory=list)
    q_delta: float = 0.0
    c_delta: float = 0.0
    authority_plane: str = "verification"
    created_at: str = field(default_factory=_now_iso)
    node_id: str | None = None
    created_by: str | None = None
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_interface_request(
    *,
    source_plane: str,
    target_plane: str,
    translation_reason: str,
    loss_notes: list[str] | None,
    certificate_refs: list[str] | None,
    q_delta: float,
    c_delta: float,
    authority_plane: str,
    node_id: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    from app.core.certificate import get_certificate
    errors.extend(validate_plane(source_plane, "source_plane"))
    errors.extend(validate_plane(target_plane, "target_plane"))

    src = normalize_plane(source_plane)
    tgt = normalize_plane(target_plane)
    if src and tgt and src == tgt:
        errors.append("source_plane and target_plane must differ; same-plane edits do not create plane interfaces")

    if not translation_reason or not translation_reason.strip():
        errors.append("translation_reason is required")

    certs = certificate_refs or []
    if not certs:
        errors.append("certificate_refs must be non-empty for cross-plane mutation")
    else:
        for cert_id in certs:
            cert = get_certificate(cert_id)
            if not cert:
                errors.append(f"certificate_ref {cert_id!r} not found")
                continue
            if cert.get("status") != "approved":
                errors.append(f"certificate_ref {cert_id!r} is not approved")
            if node_id and cert.get("node_id") != node_id:
                errors.append(f"certificate_ref {cert_id!r} node_id mismatch")

    for err in validate_authority_plane(authority_plane):
        errors.append(err)

    try:
        qd = float(q_delta)
        cd = float(c_delta)
    except Exception:
        errors.append("q_delta and c_delta must be numeric")
    else:
        if qd < -1.0 or qd > 1.0:
            errors.append("q_delta must be between -1.0 and 1.0")
        if cd < -1.0 or cd > 1.0:
            errors.append("c_delta must be between -1.0 and 1.0")

    notes = loss_notes or []
    if any(not str(n).strip() for n in notes):
        errors.append("loss_notes cannot contain blank entries")

    return {"valid": not errors, "errors": errors}


def create_interface(
    *,
    source_plane: str,
    target_plane: str,
    translation_reason: str,
    loss_notes: list[str] | None = None,
    certificate_refs: list[str] | None = None,
    q_delta: float = 0.0,
    c_delta: float = 0.0,
    authority_plane: str = "verification",
    node_id: str | None = None,
    created_by: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create and persist a cross-plane Interface artifact.

    Returns {ok, interface_id, interface, errors}. No caller should mutate a
    target plane until this function has returned ok=True.
    """
    validation = validate_interface_request(
        source_plane=source_plane,
        target_plane=target_plane,
        translation_reason=translation_reason,
        loss_notes=loss_notes,
        certificate_refs=certificate_refs,
        q_delta=q_delta,
        c_delta=c_delta,
        authority_plane=authority_plane,
        node_id=node_id,
    )
    if not validation["valid"]:
        return {"ok": False, "errors": validation["errors"], "interface_id": None}

    interface = PlaneInterface(
        interface_id=_new_interface_id(),
        source_plane=normalize_plane(source_plane),
        target_plane=normalize_plane(target_plane),
        translation_reason=translation_reason.strip(),
        loss_notes=[str(n).strip() for n in (loss_notes or [])],
        certificate_refs=list(certificate_refs or []),
        q_delta=float(q_delta),
        c_delta=float(c_delta),
        authority_plane=normalize_authority_plane(authority_plane),
        created_at=_now_iso(),
        node_id=node_id,
        created_by=created_by,
        metadata=metadata or {},
    )
    db.execute(
        """
        INSERT INTO plane_interfaces
          (interface_id, source_plane, target_plane, translation_reason,
           loss_notes_json, certificate_refs_json, q_delta, c_delta,
           authority_plane, created_at, node_id, created_by, status, metadata_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            interface.interface_id,
            interface.source_plane,
            interface.target_plane,
            interface.translation_reason,
            json.dumps(interface.loss_notes),
            json.dumps(interface.certificate_refs),
            interface.q_delta,
            interface.c_delta,
            interface.authority_plane,
            interface.created_at,
            interface.node_id,
            interface.created_by,
            interface.status,
            json.dumps(interface.metadata),
        ),
    )
    return {"ok": True, "interface_id": interface.interface_id, "interface": interface.to_dict(), "errors": []}


def _row_to_interface(row: Any) -> dict[str, Any]:
    d = dict(row)
    for key, default in (("loss_notes_json", []), ("certificate_refs_json", [])):
        try:
            d[key.replace("_json", "")] = json.loads(d.get(key) or "[]")
        except Exception:
            d[key.replace("_json", "")] = default
    try:
        d["metadata"] = json.loads(d.get("metadata_json") or "{}")
    except Exception:
        d["metadata"] = {}
    return d


def get_interface(interface_id: str) -> dict[str, Any] | None:
    row = db.fetchone("SELECT * FROM plane_interfaces WHERE interface_id=?", (interface_id,))
    return _row_to_interface(row) if row else None


def list_interfaces(node_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if node_id:
        rows = db.fetchall(
            "SELECT * FROM plane_interfaces WHERE node_id=? ORDER BY created_at DESC LIMIT ?",
            (node_id, limit),
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM plane_interfaces ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [_row_to_interface(r) for r in rows]


def latest_interface_for_transition(node_id: str, source_plane: str, target_plane: str) -> dict[str, Any] | None:
    row = db.fetchone(
        """
        SELECT * FROM plane_interfaces
        WHERE node_id=? AND source_plane=? AND target_plane=? AND status='active'
        ORDER BY created_at DESC LIMIT 1
        """,
        (node_id, normalize_plane(source_plane), normalize_plane(target_plane)),
    )
    return _row_to_interface(row) if row else None

"""app/core/authority_guard.py: Hard authority enforcement layer.

Phase 24.3 Fix A + Fix B.

Problem: human presence is not the same as legitimate authority.
Wrong clinician ≠ physician-owned resolution.
Adjacent team ≠ foreign-scope authority.
"Helpful" actor ≠ governance.

This module enforces:

    Only the declared resolution_authority may resolve.

Every resolution attempt is logged. Rejected attempts are preserved.
Failure to resolve is data. No silent bypass. No administrative override path.

Fix A — Hard authority enforcement at all resolution gates.
Fix B — Authority promotion contract with lineage.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any

from app.db import connection as db
from app.core.audit import log_event


# ---------------------------------------------------------------------------
# Authority profile and matching
# ---------------------------------------------------------------------------

@dataclass
class ActorProfile:
    actor_id: str
    actor_role: str = ""
    actor_team: str = ""
    actor_scope: str = ""
    actor_plane_authority: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def identity_tokens(self) -> list[str]:
        """All non-empty tokens that describe this actor's authority."""
        return [
            t.strip().lower() for t in [
                self.actor_id, self.actor_role,
                self.actor_team, self.actor_scope,
                self.actor_plane_authority,
            ] if t and t.strip()
        ]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_id(target_id: str, actor_id: str) -> str:
    raw = f"{target_id}|{actor_id}|{time.time_ns()}".encode()
    return "AL_" + hashlib.sha1(raw).hexdigest()[:14]


def _promotion_id(old: str, new: str) -> str:
    raw = f"{old}|{new}|{time.time_ns()}".encode()
    return "AP_" + hashlib.sha1(raw).hexdigest()[:12]


def _json_loads(v: str | None, default: Any) -> Any:
    if not v:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Fix A — Hard authority validation
# ---------------------------------------------------------------------------

def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


def _split_scope(v: Any) -> set[str]:
    raw = str(v or "").replace(",", "|").replace("/", "|")
    return {part.strip().lower() for part in raw.split("|") if part.strip()}


def _authority_contract(required_authority: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return the server-side authority contract for a resolution attempt."""
    metadata = metadata or {}
    contract = metadata.get("required_authority") or metadata.get("authority_contract") or {}
    if isinstance(contract, str):
        contract = {"resolver": contract}
    if not isinstance(contract, dict):
        contract = {}
    # Backward-compatible simple contract:
    # A bare string required_authority is treated as a required role/capability.
    # Expanded contracts enforce exact resolver identity plus team/role/scope.
    has_explicit_contract = bool(contract)
    return {
        "resolver": contract.get("resolver") or contract.get("resolver_id") or (required_authority if has_explicit_contract else ""),
        "team": contract.get("team") or contract.get("authority_domain") or "",
        "role": contract.get("role") or contract.get("required_role") or ("" if has_explicit_contract else required_authority),
        "scope": contract.get("scope") or contract.get("node_scope") or contract.get("plane_scope") or "",
        "authority_domain": contract.get("authority_domain") or contract.get("team") or "",
        "explicit_contract": has_explicit_contract,
    }


def _match_required(actual: str, required: str) -> bool:
    return bool(_norm(required)) and _norm(actual) == _norm(required)


def validate_resolution_authority(
    actor: ActorProfile,
    required_authority: str,
    target_id: str,
    target_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hard server-side authority validation.

    A canonical resolution is legitimate only when the attempting actor satisfies
    every authority dimension declared by the server-side authority contract:
    identity, team, role, and scope.
    """
    db.init_db()
    metadata = metadata or {}
    contract = _authority_contract(required_authority, metadata)
    failure_type: list[str] = []

    if contract.get("resolver") and not _match_required(actor.actor_id, contract.get("resolver", "")):
        failure_type.append("resolver")
    if contract.get("team") and not _match_required(actor.actor_team, contract["team"]):
        failure_type.append("team")
    if contract.get("role") and not _match_required(actor.actor_role, contract["role"]):
        failure_type.append("role")
    if contract.get("scope"):
        required_scope = _split_scope(contract["scope"])
        actor_scope = _split_scope(actor.actor_scope) | _split_scope(actor.actor_plane_authority)
        if not required_scope or not required_scope.issubset(actor_scope):
            failure_type.append("scope")

    authorized = len(failure_type) == 0
    failure_reason = "" if authorized else "authority_mismatch: " + ",".join(failure_type)
    result = {
        "authorized": authorized,
        "authority_valid": authorized,
        "status": "authorized" if authorized else "rejected",
        "reason": "" if authorized else "authority_mismatch",
        "failure_type": failure_type,
        "actor_id": actor.actor_id,
        "actor_authority": {
            "role": actor.actor_role,
            "team": actor.actor_team,
            "scope": actor.actor_scope,
            "plane_authority": actor.actor_plane_authority,
        },
        "required_authority": {
            "resolver": contract.get("resolver", ""),
            "team": contract.get("team", ""),
            "role": contract.get("role", ""),
            "scope": contract.get("scope", ""),
            "authority_domain": contract.get("authority_domain", ""),
        },
        "required_authority_contract": contract,
        "required_authority_raw": required_authority,
        "attempted_by": actor.actor_id,
        "canonical_lock": not authorized,
        "failure_reason": failure_reason,
        "escalation_required": not authorized,
        "target_id": target_id,
        "target_type": target_type,
    }
    _log_attempt(
        target_id=target_id,
        target_type=target_type,
        actor=actor,
        required_authority=required_authority,
        authorized=authorized,
        failure_reason=failure_reason,
        metadata={**metadata, "required_authority_contract": contract, "failure_type": failure_type},
    )
    if not authorized:
        _impose_authority_rejection_lock(
            target_id=target_id,
            reason="authority_mismatch",
            metadata={
                "failure_type": failure_type,
                "required_authority": contract,
                "attempted_by": actor.actor_id,
                "target_type": target_type,
            },
        )
    return result


def _impose_authority_rejection_lock(target_id: str, reason: str, metadata: dict[str, Any] | None = None) -> None:
    """Authority failure is a governance event and forces a canonical lock."""
    try:
        lid = "LOCK_AUTH_" + hashlib.sha1(f"{target_id}|{reason}|{time.time_ns()}".encode()).hexdigest()[:12]
        db.execute(
            """INSERT OR REPLACE INTO canonical_locks
                 (lock_id, node_id, reason, escalation_id, active, created_at, released_at, metadata_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (lid, target_id, reason, None, 1, _now_iso(), None, json.dumps(metadata or {})),
        )
    except Exception:
        pass

def _log_attempt(
    target_id: str,
    target_type: str,
    actor: ActorProfile,
    required_authority: str,
    authorized: bool,
    failure_reason: str,
    metadata: dict[str, Any],
) -> None:
    log_id = _log_id(target_id, actor.actor_id)
    db.execute(
        """INSERT INTO authority_resolution_log
             (id, target_id, target_type, actor_id, actor_role, actor_team,
              required_authority, authorization_result, failure_reason,
              timestamp, metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            log_id, target_id, target_type, actor.actor_id,
            actor.actor_role, actor.actor_team,
            required_authority,
            1 if authorized else 0,
            failure_reason,
            _now_iso(),
            json.dumps(metadata),
        ),
    )
    try:
        log_event(
            "authority_resolution_attempt",
            actor_type="human",
            actor_id=actor.actor_id,
            detail=json.dumps({
                "target_id": target_id,
                "target_type": target_type,
                "required_authority": required_authority,
                "authorized": authorized,
                "failure_reason": failure_reason,
            }),
        )
    except Exception:
        pass


def list_authority_log(
    target_id: str | None = None,
    actor_id: str | None = None,
    authorized_only: bool | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM authority_resolution_log WHERE 1=1"
    params: list[Any] = []
    if target_id:
        q += " AND target_id=?"
        params.append(target_id)
    if actor_id:
        q += " AND actor_id=?"
        params.append(actor_id)
    if authorized_only is not None:
        q += " AND authorization_result=?"
        params.append(1 if authorized_only else 0)
    q += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.fetchall(q, tuple(params))]


# ---------------------------------------------------------------------------
# Fix B — Authority promotion contract
# ---------------------------------------------------------------------------

@dataclass
class AuthorityPromotion:
    promotion_id: str
    old_authority: str
    new_authority: str
    promotion_reason: str
    approved_by: str
    target_id: str | None
    target_type: str | None
    promotion_timestamp: str
    lineage_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def promote_resolution_authority(
    old_authority: str,
    new_authority: str,
    promotion_reason: str,
    approved_by: str,
    target_id: str | None = None,
    target_type: str | None = None,
    lineage_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fix B: Explicit, signed authority promotion with lineage.

    Promotion rules:
    - Must be explicit (not inferred from inactivity or proximity)
    - Must be justified (non-empty, >= 20 chars)
    - Must be signed (approved_by is a named human)
    - Creates lineage record
    - Cannot be delegated to autonomous actors
    """
    db.init_db()
    errors: list[str] = []
    if not old_authority or not old_authority.strip():
        errors.append("old_authority is required")
    if not new_authority or not new_authority.strip():
        errors.append("new_authority is required")
    if (old_authority or "").strip().lower() == (new_authority or "").strip().lower():
        errors.append("old_authority and new_authority must differ; self-promotion is illegal")
    if not promotion_reason or len(promotion_reason.strip()) < 20:
        errors.append("promotion_reason must be substantive (>= 20 chars)")
    if not approved_by or approved_by.strip().lower() in {"auto", "autonomous", "llm", "system"}:
        errors.append("approved_by must identify a named human authority; autonomous promotion is illegal")
    if errors:
        return {"ok": False, "errors": errors}

    promo_id = _promotion_id(old_authority, new_authority)
    now = _now_iso()
    promotion = AuthorityPromotion(
        promotion_id=promo_id,
        old_authority=old_authority.strip(),
        new_authority=new_authority.strip(),
        promotion_reason=promotion_reason.strip(),
        approved_by=approved_by.strip(),
        target_id=target_id,
        target_type=target_type,
        promotion_timestamp=now,
        lineage_ref=lineage_ref,
        metadata=metadata or {},
    )
    db.execute(
        """INSERT OR REPLACE INTO authority_promotions
             (promotion_id, old_authority, new_authority, promotion_reason,
              approved_by, target_id, target_type, promotion_timestamp,
              lineage_ref, metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            promotion.promotion_id, promotion.old_authority, promotion.new_authority,
            promotion.promotion_reason, promotion.approved_by,
            promotion.target_id, promotion.target_type,
            promotion.promotion_timestamp, promotion.lineage_ref,
            json.dumps(promotion.metadata),
        ),
    )
    # If target_id is an open_item, update its resolution_authority
    if target_id and target_type == "open_item":
        db.execute(
            "UPDATE open_items SET resolution_authority=? WHERE id=?",
            (promotion.new_authority, target_id),
        )
    try:
        log_event(
            "authority_promotion",
            actor_type="human",
            actor_id=approved_by,
            detail=json.dumps(promotion.to_dict()),
        )
    except Exception:
        pass
    return {"ok": True, "promotion": promotion.to_dict()}


def get_promotion(promotion_id: str) -> dict[str, Any] | None:
    row = db.fetchone(
        "SELECT * FROM authority_promotions WHERE promotion_id=?", (promotion_id,)
    )
    if not row:
        return None
    d = dict(row)
    d["metadata"] = _json_loads(d.get("metadata_json"), {})
    return d


def list_promotions(
    target_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM authority_promotions WHERE 1=1"
    params: list[Any] = []
    if target_id:
        q += " AND target_id=?"
        params.append(target_id)
    q += " ORDER BY promotion_timestamp DESC LIMIT ?"
    params.append(limit)
    rows = db.fetchall(q, tuple(params))
    out = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json_loads(d.get("metadata_json"), {})
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Authority-gated wrappers for resolution operations
# ---------------------------------------------------------------------------

def authority_gated_resolve(
    actor: ActorProfile,
    item_id: str,
    resolution_note: str = "",
) -> dict[str, Any]:
    """Resolve an open item only if actor has the required authority."""
    db.init_db()
    row = db.fetchone("SELECT * FROM open_items WHERE id=?", (item_id,))
    if not row:
        return {"ok": False, "errors": ["open item not found"]}
    required = row["resolution_authority"]
    metadata = _json_loads(row.get("metadata_json"), {})
    context_ref = _json_loads(row.get("context_ref_json"), {})
    auth = validate_resolution_authority(
        actor, required, item_id, "open_item", {**metadata, "context_ref": context_ref}
    )
    if not auth["authorized"]:
        return {
            "ok": False,
            "status": "rejected",
            "reason": "authority_mismatch",
            "authorized": False,
            "authority_valid": False,
            "failure_type": auth.get("failure_type", []),
            "failure_reason": auth["failure_reason"],
            "required_authority": auth.get("required_authority"),
            "required_authority_raw": required,
            "attempted_by": actor.actor_id,
            "actor_authority": auth["actor_authority"],
            "escalation_required": True,
        }
    from app.core.custodian_state import normalize_custodian_state, custodian_mutation_gate
    custodian_state = normalize_custodian_state(metadata, context_ref=context_ref, valid_until=row.get("valid_until"))
    gate = custodian_mutation_gate(custodian_state, canonical_mutation=True)
    if not gate["allowed"]:
        _log_attempt(
            target_id=item_id,
            target_type="open_item",
            actor=actor,
            required_authority=required,
            authorized=False,
            failure_reason="custodian_state_block: " + ",".join(gate["failures"]),
            metadata={**metadata, "daenary_gate": gate},
        )
        return {
            "ok": False,
            "status": "rejected",
            "reason": "custodian_state_block",
            "authorized": True,
            "authority_valid": True,
            "custodian_gate": gate,
            "required_authority": auth.get("required_authority"),
            "attempted_by": actor.actor_id,
            "escalation_required": True,
        }

    from app.core.temporal_governor import resolve_open_item
    resolved = resolve_open_item(item_id, actor.actor_id, resolution_note, authority_validated=True)
    if resolved.get("ok"):
        resolved["authority_valid"] = True
        resolved["required_authority"] = auth.get("required_authority")
        resolved["actor_authority"] = auth.get("actor_authority")
    return resolved


def authority_gated_resume(
    actor: ActorProfile,
    anchor_id: str,
    active_plane: str,
    promotion_reason: str,
    required_authority: str = "governance",
) -> dict[str, Any]:
    """Resume from re-anchor only if actor has the required authority."""
    db.init_db()
    auth = validate_resolution_authority(
        actor, required_authority, anchor_id, "anchor_event"
    )
    if not auth["authorized"]:
        return {
            "ok": False,
            "authorized": False,
            "failure_reason": auth["failure_reason"],
            "required_authority": required_authority,
            "actor_authority": auth["actor_authority"],
            "escalation_required": True,
        }
    from app.core.temporal_governor import resume_on_single_plane
    return resume_on_single_plane(
        anchor_id=anchor_id,
        active_plane=active_plane,
        actor=actor.actor_id,
        promotion_reason=promotion_reason,
    )

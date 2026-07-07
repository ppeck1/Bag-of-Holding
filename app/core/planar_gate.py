"""Deterministic Planar Gate evaluator for retrieval context."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import time
from typing import Any, Literal

from app.core import planar_authority
from app.core.context_pack import (
    Posture,
    build_context_pack,
    pack_ref,
)


HIGH_RISK_OPERATIONS = {"approve", "promote", "review"}

ROLE_ALLOWED_OPERATIONS: dict[str, set[str]] = {
    "reader": {"explain", "summarize", "compare", "history", "explain_limits", "answer_context"},
    "contributor": {"explain", "summarize", "draft", "compare", "review_request", "history", "explain_limits", "answer_context"},
    "reviewer": {"explain", "summarize", "draft", "compare", "review", "review_request", "history", "explain_limits", "answer_context"},
    "approver": {"explain", "summarize", "draft", "compare", "review", "approve", "history", "explain_limits", "answer_context"},
    "domain_owner": {"explain", "summarize", "draft", "compare", "review", "approve", "promote", "review_request", "history", "explain_limits", "answer_context"},
    "schema_owner": {"review", "review_request", "explain_limits"},
    "authority_owner": {"review", "approve", "promote", "review_request", "explain_limits"},
    "llm": {"draft", "summarize", "compare", "explain", "answer_context"},
    "system_service": {"answer_context", "explain_limits"},
    "system": {"answer_context", "explain_limits"},
    "retrieval_connector": {"answer_context", "explain", "summarize", "compare", "history", "explain_limits"},
}


@dataclass
class GateResult:
    gate_result_id: str
    context_pack_id: str
    posture: Posture
    blocking_reasons: list[str] = field(default_factory=list)
    warning_reasons: list[str] = field(default_factory=list)
    allowed_context_refs: list[str] = field(default_factory=list)
    withheld_context_refs: list[str] = field(default_factory=list)
    required_route: str | None = None
    trace_event_type: str = "gate_passed"
    l6_proposal_allowed: bool = False
    l6_proposal_types: list[str] = field(default_factory=list)
    context_allowed_basis: dict[str, bool] = field(default_factory=dict)
    created_ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stable_gate_result_id(context_pack_id: str, allowed: list[str], withheld: list[str],
                           reasons: list[str]) -> str:
    raw = json.dumps(
        {
            "context_pack_id": context_pack_id,
            "allowed": allowed,
            "withheld": withheld,
            "reasons": reasons,
        },
        sort_keys=True,
    )
    return "gate_" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def _actor_role(actor: str | dict[str, Any] | None) -> str:
    if isinstance(actor, dict):
        role = actor.get("role") or actor.get("actor_role") or actor.get("actor_type") or actor.get("actor_id")
        return str(role or "reader").lower()
    return str(actor or "reader").lower()


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value or {})


def _payload(pack: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(pack.get("payload"))


def _authority(pack: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(pack.get("authority"))


def _get_first(pack: dict[str, Any], *keys: str) -> Any:
    payload = _payload(pack)
    authority = _authority(pack)
    for key in keys:
        if pack.get(key) not in (None, ""):
            return pack.get(key)
        if payload.get(key) not in (None, ""):
            return payload.get(key)
        if authority.get(key) not in (None, ""):
            return authority.get(key)
    return None


def _blocked_use(pack: dict[str, Any]) -> set[str]:
    value = _get_first(pack, "blocked_use")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(v) for v in value}
    return set()


def _is_stale(pack: dict[str, Any]) -> bool:
    status = str(_get_first(pack, "temporal_status") or "").lower()
    if status in {"stale", "expired"}:
        return True
    valid_until = _get_first(pack, "valid_until")
    if not valid_until:
        return False
    try:
        return datetime.fromisoformat(str(valid_until).replace("Z", "+00:00")).timestamp() < time.time()
    except Exception:
        return False


def _unknown_source_trust(pack: dict[str, Any]) -> bool:
    source_trust = str(_get_first(pack, "source_trust") or "").lower()
    if source_trust in {"unknown", "low", "untrusted"}:
        return True
    if str(_get_first(pack, "object_status") or "").lower() == "imported":
        return True
    return str(_get_first(pack, "authority_ref") or "") == "auth_unknown_import"


def _scalar_basis_missing(pack: dict[str, Any]) -> bool:
    return not bool(_get_first(pack, "scalar_basis_ref"))


def _has_open_conflict(pack: dict[str, Any], context_pack: dict[str, Any]) -> bool:
    return bool(
        context_pack.get("conflict_set_ref")
        or _get_first(pack, "conflict_set_ref")
        or pack.get("conflicts")
    )


def _role_allows(actor: str | dict[str, Any] | None, operation: str) -> bool:
    role = _actor_role(actor)
    if role.startswith(("llm", "ollama", "model")):
        role = "llm"
    allowed = ROLE_ALLOWED_OPERATIONS.get(role)
    if allowed is None:
        return operation in ROLE_ALLOWED_OPERATIONS["reader"]
    return operation in allowed


def _resolve_posture(operation: str, blocking: list[str], warnings: list[str],
                     required_route: str | None) -> Posture:
    if blocking:
        return "blocked"
    if required_route in {"schema_review", "review_queue", "authority_review"}:
        return "review_required"
    if warnings:
        return "bounded"
    return "answerable"


def evaluate_context_pack(
    *,
    query: str,
    operation: str,
    actor: str | dict[str, Any] | None,
    mode: str,
    candidate_packs: list[dict[str, Any]],
    governance_health: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return deterministic ContextPack and GateResult dictionaries."""
    operation_key = str(operation or "answer_context").lower()
    governance_health = governance_health or {}
    context = build_context_pack(
        query=query,
        operation=operation_key,
        actor=actor,
        mode=mode,
        candidate_packs=candidate_packs,
        conflict_set_ref=governance_health.get("conflict_set_ref"),
        dominance_policy_ref=governance_health.get("dominance_policy_ref"),
        governance_health_ref=governance_health.get("governance_health_ref"),
    ).to_dict()

    blocking: list[str] = []
    warnings: list[str] = []
    allowed_refs: list[str] = []
    withheld_refs: list[str] = []
    basis: dict[str, bool] = {}
    required_route: str | None = None
    l6_proposal_types: list[str] = []

    if not _role_allows(actor, operation_key):
        blocking.append("actor_role_operation_denied")
        required_route = "authority_review"

    if context["missing_planes"]:
        reason = "rct_expected_planes_missing"
        if operation_key in {"approve", "promote"}:
            blocking.append(reason)
            required_route = required_route or "review_queue"
        else:
            warnings.append(reason)

    for pack in candidate_packs:
        ref = pack_ref(pack)
        pack_allowed = True
        if str(pack.get("plane") or "").lower() == "subjective":
            warnings.append("subjective_card")
        decision = pack.get("eligibility")
        if not decision:
            card_like = {
                "id": pack.get("card_id"),
                "doc_id": pack.get("doc_id"),
                "plane": pack.get("plane"),
                "payload": {
                    "non_authoritative": pack.get("do_not_treat_as_canonical"),
                    "confidence": (pack.get("why_selected") or {}).get("semantic_score"),
                },
                "authority": {"state": pack.get("authority_state")},
                "valid_until": _get_first(pack, "valid_until"),
            }
            decision = planar_authority.can_use(actor, card_like, operation_key, mode).to_dict()
        if not decision.get("allowed", True):
            pack_allowed = False
            warnings.append(f"authority:{decision.get('reason') or 'denied'}")

        if operation_key in _blocked_use(pack):
            pack_allowed = False
            if operation_key in HIGH_RISK_OPERATIONS:
                blocking.append("blocked_use")
            else:
                warnings.append("blocked_use")
            required_route = required_route or "review_queue"

        if _is_stale(pack):
            if operation_key in HIGH_RISK_OPERATIONS:
                pack_allowed = False
                blocking.append("temporal_stale_high_risk")
                required_route = required_route or "review_queue"
            else:
                warnings.append("staleness_must_be_disclosed")

        if _unknown_source_trust(pack):
            if operation_key in {"approve", "promote"}:
                pack_allowed = False
                blocking.append("source_trust_unknown_quarantine")
                warnings.append("source_poisoning_threat_control_applied")
                required_route = required_route or "authority_review"
            elif operation_key in {"review", "review_request", "explain_limits"}:
                warnings.append("source_trust_unknown_quarantine")

        if operation_key in {"approve", "promote"} and _scalar_basis_missing(pack):
            pack_allowed = False
            blocking.append("scalar_basis_missing")
            l6_proposal_types.extend(["scalar_recalibration", "fixture_patch"])
            required_route = required_route or "review_queue"

        if _has_open_conflict(pack, context):
            if operation_key in {"approve", "promote"} and not context.get("dominance_policy_ref"):
                pack_allowed = False
                blocking.append("decision_basis_missing")
                required_route = required_route or "review_queue"
            else:
                warnings.append("conflict_disclosed")

        if ref:
            basis[ref] = bool(pack_allowed)
            if pack_allowed:
                allowed_refs.append(ref)
            else:
                withheld_refs.append(ref)

    blocking = list(dict.fromkeys(blocking))
    warnings = list(dict.fromkeys(warnings))
    allowed_refs = list(dict.fromkeys(allowed_refs))
    withheld_refs = list(dict.fromkeys(withheld_refs))
    posture = _resolve_posture(operation_key, blocking, warnings, required_route)
    trace = "gate_blocked" if posture == "blocked" else "gate_degraded" if posture in {"bounded", "review_required"} else "gate_passed"
    result = GateResult(
        gate_result_id=_stable_gate_result_id(context["context_pack_id"], allowed_refs, withheld_refs, blocking + warnings),
        context_pack_id=context["context_pack_id"],
        posture=posture,
        blocking_reasons=blocking,
        warning_reasons=warnings,
        allowed_context_refs=allowed_refs,
        withheld_context_refs=withheld_refs,
        required_route=required_route,
        trace_event_type=trace,
        l6_proposal_allowed=bool(l6_proposal_types),
        l6_proposal_types=list(dict.fromkeys(l6_proposal_types)),
        context_allowed_basis=basis,
    )
    return context, result.to_dict()


def compare_expected_actual(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    mismatches = []
    for key in ("posture", "required_route", "trace_event_type", "l6_proposal_allowed"):
        if expected.get(key) != actual.get(key):
            mismatches.append({"field": key, "expected": expected.get(key), "actual": actual.get(key)})
    for key in ("blocking_reasons", "warning_reasons", "allowed_context_refs", "withheld_context_refs"):
        expected_set = set(expected.get(key) or [])
        actual_set = set(actual.get(key) or [])
        if not expected_set.issubset(actual_set):
            mismatches.append({"field": key, "missing": sorted(expected_set - actual_set)})
    return {"passed": not mismatches, "mismatches": mismatches}

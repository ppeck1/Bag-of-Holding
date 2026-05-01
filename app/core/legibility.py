"""app/core/legibility.py: User Legibility Layer.

Phase 26D — Trust must be explainable.

Problem:
    The backend is rigorous. The user-facing explanation is not yet sufficient.
    Most users do not need epistemic theory. They need legible trust.

    BAD:  "Access denied"
    GOOD: "Canonical promotion blocked. Reason: Scope legitimacy failure.
           Attempted by: Review authority. Required: Clinical Canon Custodian.
           Current State: Contained. Next Path: Custodian resolution."

This module translates every blocked action into a structured, legible explanation:
    - WHY was this blocked? (specific, not generic)
    - WHO must resolve it? (named, not abstract)
    - WHAT is the escalation state? (current governance level)
    - WHAT happens next? (concrete path forward)
    - WHY can I not override it? (machine truth, not policy language)

Usage:
    from app.core.legibility import explain_block, explain_sc3_block

    # On authority rejection:
    explanation = explain_block(authority_result)

    # On SC3 constitutive block:
    explanation = explain_sc3_block(sc3_result)

    # On Daenary custodian block:
    explanation = explain_daenary_block(daenary_gate_result)

    # Generic blocked action with any result dict:
    explanation = explain_any_block(result, action_type="canonical_promotion")
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Authority mismatch explanations
# ---------------------------------------------------------------------------

_FAILURE_TYPE_EXPLANATIONS: dict[str, str] = {
    "resolver": (
        "The specific resolver identity declared for this item does not match "
        "the attempting actor. This is an identity failure: the wrong individual "
        "attempted a resolver-specific canonical action."
    ),
    "team": (
        "The attempting actor belongs to a different authority domain than required. "
        "Adjacent teams cannot perform cross-domain canonical mutations, even when "
        "the actor is otherwise a valid governance participant."
    ),
    "role": (
        "The actor's governance role does not satisfy the required role for this action. "
        "A reviewer cannot execute resolver actions. An observer cannot transfer custody. "
        "Roles are constitutive, not advisory."
    ),
    "scope": (
        "The actor's authorized scope does not cover this node. Scope legitimacy is "
        "a hard boundary: authorized resolvers can only mutate nodes within their "
        "registered scope. Cross-scope mutation is blocked regardless of other authority."
    ),
}

_ESCALATION_STATE_LABELS: dict[str, str] = {
    "warning": "⚠️  Warning — First governance signal. Resolution possible without escalation.",
    "contain": "🔒 Contained — Active governance boundary. Canonical lock imposed.",
    "forced_escalation": "🚨 Forced Escalation — Authority has been transferred. Supervisor resolution required.",
    "locked": "🔐 Canonical Lock — Mutation blocked until legitimate resolver acts.",
    "resolved": "✅ Resolved — Governance event closed.",
}


def explain_block(authority_result: dict[str, Any]) -> dict[str, Any]:
    """Produce a legible explanation for an authority rejection.

    Input: the result dict from validate_resolution_authority() or authority_gated_resolve()
    Output: structured legibility payload for the user interface
    """
    failure_types: list[str] = authority_result.get("failure_type", [])
    required_authority: dict[str, Any] = authority_result.get("required_authority") or {}
    actor_authority: dict[str, Any] = authority_result.get("actor_authority") or {}
    escalation_state: str = _infer_escalation_state(authority_result)

    # Why blocked
    why_parts = []
    for ft in failure_types:
        why_parts.append(f"• {ft.upper()}: {_FAILURE_TYPE_EXPLANATIONS.get(ft, 'Authority dimension mismatch.')}")
    why_blocked = (
        "\n".join(why_parts)
        if why_parts
        else "Authority validation failed. No specific failure dimension recorded."
    )

    # Who must resolve
    required_resolver = (
        required_authority.get("resolver")
        or required_authority.get("team")
        or required_authority.get("role")
        or authority_result.get("required_authority_raw")
        or "Declared resolution authority"
    )
    if required_authority.get("team") and required_authority.get("role"):
        who_must_resolve = (
            f"{required_authority['role'].title()} from {required_authority['team'].title()} team"
        )
    elif required_authority.get("resolver"):
        who_must_resolve = f"Specifically: {required_authority['resolver']}"
    elif required_authority.get("role"):
        who_must_resolve = f"{required_authority['role'].title()} role"
    elif required_authority.get("team"):
        who_must_resolve = f"{required_authority['team'].title()} team"
    else:
        who_must_resolve = required_resolver

    # What is the escalation state
    escalation_label = _ESCALATION_STATE_LABELS.get(
        escalation_state,
        f"Governance state: {escalation_state}"
    )

    # What happens next
    next_path = _next_path(failure_types, escalation_state, required_authority)

    # Why override impossible
    why_override_impossible = (
        "This is a constitutive governance boundary. "
        "The authority contract is server-side enforced and cannot be bypassed by the client. "
        "Canonical truth requires legitimate resolver action. "
        "The system does not accept administrative workarounds: every failure is a permanent "
        "governance event in the authority resolution log."
    )

    # Actor context
    attempted_by = authority_result.get("attempted_by") or authority_result.get("actor_id") or "unknown"
    actor_role = actor_authority.get("role") or "unspecified role"
    actor_team = actor_authority.get("team") or "unspecified team"
    actor_scope = actor_authority.get("scope") or "no scope registered"

    return {
        "legible": True,
        "blocked": True,
        "title": "Canonical Action Blocked",
        "subtitle": _block_subtitle(failure_types),
        "why_blocked": why_blocked,
        "failure_dimensions": failure_types,
        "who_must_resolve": who_must_resolve,
        "escalation_state": escalation_state,
        "escalation_label": escalation_label,
        "next_path": next_path,
        "why_override_impossible": why_override_impossible,
        "attempted_by": attempted_by,
        "actor_context": {
            "role": actor_role,
            "team": actor_team,
            "scope": actor_scope,
        },
        "required_authority_summary": {
            "resolver": required_authority.get("resolver", ""),
            "role": required_authority.get("role", ""),
            "team": required_authority.get("team", ""),
            "scope": required_authority.get("scope", ""),
        },
        "audit_note": (
            "This rejection is permanently recorded in the authority resolution log. "
            "It is governance data, not an error. The rejection event cannot be deleted."
        ),
    }


def explain_sc3_block(sc3_result: dict[str, Any]) -> dict[str, Any]:
    """Produce a legible explanation for an SC3 constitutive block (plane mismatch)."""
    source_plane = sc3_result.get("source_plane", "unknown")
    target_plane = sc3_result.get("target_plane", "unknown")
    required_resolver = sc3_result.get("required_resolver", "Appropriate Canon Custodian")
    severity = sc3_result.get("severity", "medium")
    explanation = sc3_result.get("explanation", "")
    next_path = sc3_result.get("next_path", "Custodian review required.")
    why_override = sc3_result.get("why_override_impossible", "SC3 constitutive boundary.")

    _plane_desc = {
        "physical": "empirical / sensor / measurement data",
        "informational": "structured knowledge / policy / codified facts",
        "subjective": "interpretation / inference / LLM synthesis / opinion",
    }

    why_blocked = (
        f"SC3 Plane Hierarchy Violation.\n"
        f"• Source: {source_plane.upper()} plane ({_plane_desc.get(source_plane, source_plane)})\n"
        f"• Target: {target_plane.upper()} plane ({_plane_desc.get(target_plane, target_plane)})\n"
        f"• Rule: {source_plane.capitalize()} evidence cannot directly overwrite "
        f"{target_plane.capitalize()} canon. The epistemic authority of the source "
        f"is insufficient for the target canonical layer."
    )

    severity_labels = {
        "critical": "🚨 Critical — Subjective inference attempting to overwrite physical canon.",
        "high": "⚠️  High — Subjective inference attempting to overwrite structured knowledge.",
        "medium": "⚠️  Medium — Cross-plane promotion without sufficient epistemic authority.",
        "none": "✅ Pass — No plane mismatch detected.",
    }

    return {
        "legible": True,
        "blocked": True,
        "title": "Canonical Promotion Blocked: SC3 Plane Mismatch",
        "subtitle": severity_labels.get(severity, f"SC3 violation: {severity}"),
        "why_blocked": why_blocked,
        "failure_dimensions": ["sc3_plane_mismatch"],
        "who_must_resolve": required_resolver,
        "escalation_state": "locked",
        "escalation_label": _ESCALATION_STATE_LABELS["locked"],
        "next_path": next_path,
        "why_override_impossible": why_override,
        "sc3_detail": {
            "source_plane": source_plane,
            "target_plane": target_plane,
            "severity": severity,
            "full_explanation": explanation,
        },
        "audit_note": (
            "This SC3 violation is permanently recorded. "
            "SC3 constitutive boundaries are architectural, not advisory. "
            "The plane hierarchy cannot be bypassed client-side."
        ),
    }


def explain_daenary_block(daenary_gate: dict[str, Any]) -> dict[str, Any]:
    """Produce a legible explanation for a Daenary custodian state block."""
    failures = daenary_gate.get("failures") or daenary_gate.get("block_reasons") or []
    state = daenary_gate.get("state") or daenary_gate.get("custodian_state") or "unknown"

    failure_parts = []
    _daenary_failure_map: dict[str, str] = {
        "active_canonical_lock": (
            "An active canonical lock is imposed on this node. "
            "No mutation is permitted until the lock is explicitly released by a legitimate resolver."
        ),
        "forced_escalation_active": (
            "This node is under forced escalation. "
            "Authority has been transferred. The original resolver no longer has standing."
        ),
        "containment_active": (
            "This node is in containment. "
            "Canonical mutation is suspended pending escalation resolution."
        ),
        "expired_validity": (
            "The authority window for this node has expired. "
            "Temporal validity is a constitutive boundary: stale authority cannot be used."
        ),
        "custody_suspended": (
            "Custodianship is suspended for this node. "
            "No mutation is permitted without an explicit custody transfer."
        ),
        "review_pending": (
            "A pending review decision has not yet been rendered. "
            "Canonical mutation is blocked until the review concludes."
        ),
    }

    for f in failures:
        failure_parts.append(f"• {f.upper()}: {_daenary_failure_map.get(f, 'Custodian state violation.')}")
    why_blocked = (
        "\n".join(failure_parts)
        if failure_parts
        else f"Daenary custodian state '{state}' blocks canonical mutation."
    )

    return {
        "legible": True,
        "blocked": True,
        "title": "Canonical Mutation Blocked: Daenary State",
        "subtitle": f"Current custodian state: {state.upper()}",
        "why_blocked": why_blocked,
        "failure_dimensions": failures,
        "who_must_resolve": "Declared custodian or escalation supervisor",
        "escalation_state": _map_daenary_state_to_escalation(state, failures),
        "escalation_label": _ESCALATION_STATE_LABELS.get(
            _map_daenary_state_to_escalation(state, failures),
            f"Daenary state: {state}"
        ),
        "next_path": (
            "Resolve the active custodian state: "
            "release canonical lock, resolve escalation, or transfer custody. "
            "Authority-gated resolution required."
        ),
        "why_override_impossible": (
            "Daenary state is a constitutive boundary enforced by the custodian gate. "
            "State transitions require legitimate actor action through the governance chain. "
            "Client-side override is architecturally impossible."
        ),
        "audit_note": (
            "This block is recorded by the authority guard. "
            "Daenary state failures are permanent governance events."
        ),
    }


def explain_any_block(
    result: dict[str, Any],
    action_type: str = "unknown_action",
) -> dict[str, Any]:
    """Universal legibility wrapper for any blocked result dict.

    Detects the block type and delegates to the appropriate explainer.
    Falls back to a generic legible explanation if type is ambiguous.
    """
    # SC3 block
    if result.get("sc3_blocked") or result.get("plane_mismatch"):
        return explain_sc3_block(result)

    # Daenary block
    if result.get("reason") == "custodian_state_block" or result.get("custodian_gate"):
        gate = result.get("custodian_gate") or result
        return explain_daenary_block(gate)

    # Authority block
    if (
        result.get("reason") == "authority_mismatch"
        or result.get("failure_type")
        or result.get("authorized") is False
    ):
        return explain_block(result)

    # Generic block
    return {
        "legible": True,
        "blocked": True,
        "title": f"Action Blocked: {action_type.replace('_', ' ').title()}",
        "subtitle": result.get("reason") or result.get("status") or "Unknown governance block",
        "why_blocked": (
            result.get("message")
            or result.get("error")
            or result.get("detail")
            or "The system blocked this action. Check the governance log for details."
        ),
        "failure_dimensions": [],
        "who_must_resolve": "Appropriate authority (see governance log)",
        "escalation_state": "locked",
        "escalation_label": _ESCALATION_STATE_LABELS["locked"],
        "next_path": "Review the governance log for this node and follow the authority chain.",
        "why_override_impossible": (
            "This action is governed by constitutive boundaries. "
            "The block is system-enforced, not advisory."
        ),
        "audit_note": "Check authority_resolution_log and governance_events for the full record.",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _block_subtitle(failure_types: list[str]) -> str:
    if not failure_types:
        return "Authority Validation Failed"
    labels = {
        "resolver": "Wrong Identity",
        "team": "Wrong Authority Domain",
        "role": "Insufficient Role",
        "scope": "Out of Scope",
    }
    parts = [labels.get(f, f.replace("_", " ").title()) for f in failure_types]
    return "Failure: " + " + ".join(parts)


def _infer_escalation_state(result: dict[str, Any]) -> str:
    if result.get("canonical_lock"):
        return "locked"
    if result.get("escalation_required"):
        return "contain"
    if result.get("status") == "authorized":
        return "resolved"
    return "contain"


def _next_path(
    failure_types: list[str],
    escalation_state: str,
    required_authority: dict[str, Any],
) -> str:
    resolver_str = (
        required_authority.get("resolver")
        or required_authority.get("role")
        or required_authority.get("team")
        or "declared resolution authority"
    )

    if escalation_state == "forced_escalation":
        return (
            f"Forced escalation is active. The supervisor must resolve this governance event. "
            f"Original resolver ({resolver_str}) no longer has standing."
        )
    if "scope" in failure_types:
        return (
            f"Scope mismatch. The actor must be granted scope authority over this node, "
            f"or the item must be transferred to an actor with the correct scope. "
            f"Required: {resolver_str}."
        )
    if "team" in failure_types:
        return (
            f"Escalate to the correct authority domain. "
            f"The action must be attempted by {resolver_str}. "
            f"Cross-domain delegation is not permitted."
        )
    if "resolver" in failure_types:
        return (
            f"Only the declared resolver ({resolver_str}) may act. "
            f"No delegation or proxy is accepted. "
            f"If the resolver is unavailable, initiate authority promotion with signed justification."
        )
    if "role" in failure_types:
        return (
            f"The actor requires the correct role ({resolver_str}) to perform this action. "
            f"Role escalation requires explicit governance approval."
        )
    return (
        f"Contact the required resolver ({resolver_str}) to proceed. "
        f"If the resolver is unavailable, escalate through the governance chain."
    )


def _map_daenary_state_to_escalation(state: str, failures: list[str]) -> str:
    if "forced_escalation_active" in failures:
        return "forced_escalation"
    if "active_canonical_lock" in failures or "containment_active" in failures:
        return "contain"
    if state in ("warning", "warn"):
        return "warning"
    return "locked"

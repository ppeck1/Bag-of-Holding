"""app/core/custodian.py: Daenary Custodian Layer for Bag of Holding v2.

Phase 18: Epistemic custody — answers before any canonical mutation:

  What is being changed?         → mutation_reason + evidence_refs
  Why is it allowed?             → d / m / correction_status contract
  What confidence supports it?   → epistemic_c
  What evidence quality?         → epistemic_q
  What expires?                  → valid_until check
  What gets contained?           → d=0, m=contain routing
  What gets canceled?            → d=0, m=cancel routing
  What is the cost if wrong?     → meaning_cost gate

Design invariants:
  - Cannot canonicalize an expired node (valid_until in past)
  - Cannot canonicalize d=0 without m
  - Cannot canonicalize cancel state (m=cancel)
  - Cannot canonicalize when meaning_cost.total is critical without human review
  - contain and cancel nodes remain fully searchable and visible
  - All custody decisions write to custodian_review_state
  - All custody operations are deterministic and rule-based
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from app.db import connection as db

# ── Epistemic contract constants ───────────────────────────────────────────────

VALID_D_VALUES  = {-1, 0, 1, None}
VALID_M_VALUES  = {"contain", "cancel", None}
VALID_CORRECTION_STATUSES = {
    "accurate", "incomplete", "outdated", "conflicting", "likely_incorrect",
}

# Promotion thresholds by cost tier
CANON_THRESHOLDS = {
    "low":      {"q": 0.65, "c": 0.60},
    "moderate": {"q": 0.75, "c": 0.70},
    "high":     {"q": 0.85, "c": 0.80},  # also requires human review flag
    "critical": None,                       # no auto-canonicalization
}

DECISION_MODES = {"understand", "decide", "escalate", "defer", "reject"}


# ── Meaning-cost computation ───────────────────────────────────────────────────

def compute_meaning_cost(doc: dict, justification: dict | None = None) -> dict:
    """Compute meaning_cost for a document or mutation request.

    Inputs from doc metadata and optional justification dict.
    All components are floats 0.0–1.0. Total is a weighted sum.
    """
    j = justification or {}
    cost_override = j.get("cost_if_wrong") or {}

    # Base components — derived from document epistemic state
    q = float(doc.get("epistemic_q") or 0.0)
    c = float(doc.get("epistemic_c") or 0.0)
    correction = doc.get("epistemic_correction_status") or "incomplete"
    is_canonical = (doc.get("canonical_layer") or doc.get("status") or "") == "canonical"

    # Processing cost: inversely proportional to q (low quality = high processing needed)
    processing = round(max(0.0, 1.0 - q) * 0.6, 3)

    # Time cost: higher when material is outdated or has no valid_until
    vuntil = doc.get("epistemic_valid_until")
    if vuntil:
        try:
            exp = datetime.fromisoformat(vuntil.replace("Z", "+00:00"))
            now = datetime.now(tz=timezone.utc)
            days_past = (now - exp).days if exp < now else 0
            time_cost = round(min(1.0, days_past / 30.0), 3)
        except Exception:
            time_cost = 0.2
    else:
        time_cost = 0.2 if not is_canonical else 0.0

    # Harm cost: from justification or derived from correction_status
    harm_cost = float(cost_override.get("harm_cost", {
        "accurate":        0.0,
        "incomplete":      0.2,
        "outdated":        0.4,
        "conflicting":     0.7,
        "likely_incorrect": 0.9,
    }.get(correction, 0.3)))

    # Reversal cost: harder to reverse canonical docs
    reversal_cost = float(cost_override.get("reversal_cost", 0.6 if is_canonical else 0.2))

    # Escalation cost: low confidence + high harm = escalation burden
    escalation = round(min(1.0, (1.0 - c) * harm_cost), 3)

    # Opportunity cost: cost of NOT acting (low if doc is just noise)
    opportunity = float(cost_override.get("opportunity_cost", max(0.0, q * 0.4)))

    # Weighted total
    total = round(
        processing  * 0.15 +
        time_cost   * 0.10 +
        escalation  * 0.25 +
        harm_cost   * 0.30 +
        reversal_cost * 0.15 +
        opportunity * 0.05,
        3,
    )

    return {
        "processing":    processing,
        "time":          time_cost,
        "escalation":    escalation,
        "harm_if_wrong": harm_cost,
        "reversal":      reversal_cost,
        "opportunity":   opportunity,
        "total":         total,
    }


def cost_tier(total: float) -> str:
    """Map a meaning_cost.total to a named cost tier."""
    if total < 0.30:  return "low"
    if total < 0.55:  return "moderate"
    if total < 0.75:  return "high"
    return "critical"


# ── Epistemic contract validation ──────────────────────────────────────────────

def check_epistemic_contract(doc: dict) -> dict:
    """Validate that a document's epistemic state satisfies the Daenary contract.

    Returns {valid: bool, errors: list[str]}.
    Non-fatal warnings are separate from blocking errors.
    """
    errors: list[str] = []
    warnings: list[str] = []

    d = doc.get("epistemic_d")
    m = doc.get("epistemic_m")
    q = doc.get("epistemic_q")
    c = doc.get("epistemic_c")
    correction = doc.get("epistemic_correction_status")
    vuntil = doc.get("epistemic_valid_until")

    # Rule: m is required when d == 0
    if d == 0 and m is None:
        errors.append("d=0 requires m to be set ('contain' or 'cancel')")

    # Rule: m must be null when d != 0
    if d is not None and d != 0 and m is not None:
        errors.append(f"m must be null when d={d} (non-zero d has no zero-mode)")

    # Rule: q and c must be 0.0–1.0 when present
    if q is not None and not (0.0 <= float(q) <= 1.0):
        errors.append(f"epistemic_q={q} is out of range [0.0, 1.0]")
    if c is not None and not (0.0 <= float(c) <= 1.0):
        errors.append(f"epistemic_c={c} is out of range [0.0, 1.0]")

    # Rule: correction_status must be a valid value when present
    if correction and correction not in VALID_CORRECTION_STATUSES:
        errors.append(f"Unknown correction_status: {correction!r}")

    # Warning: non-canonical imported material should have valid_until
    status = (doc.get("status") or "").lower()
    layer  = (doc.get("canonical_layer") or "").lower()
    is_canonical = layer == "canonical" or status == "canonical"
    if not is_canonical and d is not None and vuntil is None:
        warnings.append("Non-canonical document with epistemic state should set valid_until")

    # Warning: expired valid_until
    if vuntil:
        try:
            exp = datetime.fromisoformat(vuntil.replace("Z", "+00:00"))
            now = datetime.now(tz=timezone.utc)
            if exp < now:
                warnings.append(f"valid_until={vuntil} has expired")
        except Exception:
            warnings.append(f"valid_until={vuntil!r} could not be parsed as ISO date")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


# ── Canonicalization gate ──────────────────────────────────────────────────────

def can_canonicalize(doc: dict, justification: dict | None = None) -> dict:
    """Gate: may this document be promoted to canonical status?

    Returns {allowed: bool, reason: str, route: str, decision_mode: str,
             cost: dict, tier: str, contract: dict}.

    All blocking conditions are enumerated before returning allowed=False.
    """
    j = justification or {}
    errors: list[str] = []

    d  = doc.get("epistemic_d")
    m  = doc.get("epistemic_m")
    q  = doc.get("epistemic_q")
    c  = doc.get("epistemic_c")
    correction = doc.get("epistemic_correction_status")
    vuntil = doc.get("epistemic_valid_until")

    # Rule 1: Cannot canonicalize expired node
    if vuntil:
        try:
            exp = datetime.fromisoformat(vuntil.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(tz=timezone.utc):
                errors.append(f"Node is expired (valid_until={vuntil}). Require fresh evidence.")
        except Exception:
            pass

    # Rule 2: Cannot canonicalize d=0 without m
    if d == 0 and m is None:
        errors.append("d=0 without m — epistemic state unresolved. Set m=contain or m=cancel.")

    # Rule 3: Cannot canonicalize cancel state
    if m == "cancel":
        errors.append("m=cancel — this node contains contradicted information. Cannot promote.")

    # Rule 4: Cannot canonicalize likely_incorrect
    if correction == "likely_incorrect":
        errors.append("correction_status=likely_incorrect blocks canonical promotion.")

    # Rule 5: Cannot canonicalize conflicting without resolution
    if correction == "conflicting":
        errors.append("correction_status=conflicting — contradiction unresolved. Resolve before promotion.")

    # Compute meaning cost
    cost = compute_meaning_cost(doc, j)
    tier = cost_tier(cost["total"])

    # Rule 6: Quality / confidence thresholds by cost tier
    thresholds = CANON_THRESHOLDS.get(tier)
    if thresholds is None:
        errors.append(f"meaning_cost.total={cost['total']:.3f} is critical — no auto-canonicalization allowed.")
    else:
        q_val = float(q) if q is not None else 0.0
        c_val = float(c) if c is not None else 0.0
        if q_val < thresholds["q"]:
            errors.append(f"epistemic_q={q_val:.2f} < {thresholds['q']} threshold for {tier}-cost promotion.")
        if c_val < thresholds["c"]:
            errors.append(f"epistemic_c={c_val:.2f} < {thresholds['c']} threshold for {tier}-cost promotion.")

    # Rule 7: High-cost requires human review flag in justification
    if tier == "high" and not j.get("human_reviewed"):
        errors.append("High-cost promotion requires human_reviewed=true in justification.")

    # Determine decision mode — priority: reject > defer > escalate > contain
    if errors:
        if m == "cancel" or correction in {"conflicting"}:
            # Contradiction / cancel always routes to reject — even if cost is high
            route = "reject"
            decision_mode = "reject"
        elif vuntil and any("expired" in e for e in errors):
            route = "defer"
            decision_mode = "defer"
        elif tier == "critical" or cost.get("harm_if_wrong", 0) >= 0.7:
            route = "escalate"
            decision_mode = "escalate"
        else:
            route = "contain"
            decision_mode = "understand"
    else:
        route = "canonical"
        decision_mode = j.get("decision_mode", "decide")

    contract = check_epistemic_contract(doc)

    return {
        "allowed":       len(errors) == 0,
        "errors":        errors,
        "reason":        errors[0] if errors else "All canonical promotion gates passed.",
        "route":         route,
        "decision_mode": decision_mode,
        "cost":          cost,
        "tier":          tier,
        "contract":      contract,
    }


# ── Mutation evaluation ────────────────────────────────────────────────────────

def evaluate_mutation(
    doc: dict,
    mutation_reason: str,
    evidence_refs: list[str] | None = None,
    q: float | None = None,
    c: float | None = None,
    d: int | None = None,
    m: str | None = None,
    cost_if_wrong: dict | None = None,
    decision_mode: str = "understand",
    human_reviewed: bool = False,
) -> dict:
    """Evaluate a proposed canonical mutation against all custodian gates.

    Returns the full custodian verdict with route and decision.
    Writes the custodian_review_state to the doc's DB record if doc_id present.
    """
    if not mutation_reason or not mutation_reason.strip():
        return {
            "allowed": False,
            "reason": "mutation_reason is required for all canonical mutations.",
            "route": "reject",
            "decision_mode": "reject",
        }

    if decision_mode not in DECISION_MODES:
        return {
            "allowed": False,
            "reason": f"Unknown decision_mode: {decision_mode!r}. Valid: {sorted(DECISION_MODES)}",
            "route": "reject",
            "decision_mode": "reject",
        }

    # Build justification context
    justification = {
        "mutation_reason": mutation_reason,
        "evidence_refs":   evidence_refs or [],
        "decision_mode":   decision_mode,
        "human_reviewed":  human_reviewed,
        "cost_if_wrong":   cost_if_wrong or {},
    }

    # Override doc epistemic fields with provided values for the purpose of evaluation
    eval_doc = dict(doc)
    if q is not None: eval_doc["epistemic_q"] = q
    if c is not None: eval_doc["epistemic_c"] = c
    if d is not None: eval_doc["epistemic_d"] = d
    if m is not None: eval_doc["epistemic_m"] = m

    result = can_canonicalize(eval_doc, justification)
    result["mutation_reason"]  = mutation_reason
    result["evidence_refs"]    = evidence_refs or []
    result["requested_mode"]   = decision_mode
    result["evaluated_at"]     = datetime.now(tz=timezone.utc).isoformat()

    # Persist custodian state if we have a doc_id
    doc_id = doc.get("doc_id") or doc.get("id")
    if doc_id:
        new_state = result["route"]
        try:
            db.execute(
                "UPDATE docs SET custodian_review_state=? WHERE doc_id=?",
                (new_state, doc_id),
            )
        except Exception:
            pass

    return result


# ── State routing helpers ──────────────────────────────────────────────────────

def route_zero_mode(doc: dict) -> str:
    """For a d=0 document, determine contain vs cancel routing.

    Contradiction evidence → cancel.
    Ambiguity / insufficient evidence → contain.
    """
    correction = doc.get("epistemic_correction_status") or ""
    if correction in {"conflicting", "likely_incorrect"}:
        return "cancel"
    return "contain"


def get_custodian_lane(doc: dict) -> str:
    """Map a document to its custodian governance lane (Phase 18 constitutional topology).

    Lanes (in ascending authority order):
      raw_imported  — no epistemic state at all
      expired       — valid_until in past
      canceled      — d=0, m=cancel
      contained     — d=0, m=contain
      under_review  — has epistemic state, correction not accurate
      approved      — q/c thresholds met for low-cost tier
      canonical     — canonical_layer=canonical or status=canonical
      archived      — archived / superseded
    """
    d          = doc.get("epistemic_d")
    m          = doc.get("epistemic_m")
    q          = doc.get("epistemic_q")
    c          = doc.get("epistemic_c")
    correction = doc.get("epistemic_correction_status")
    vuntil     = doc.get("epistemic_valid_until")
    layer      = (doc.get("canonical_layer") or "").lower()
    status     = (doc.get("status") or "").lower()
    auth       = (doc.get("authority_state") or "").lower()
    cust_state = (doc.get("custodian_review_state") or "").lower()

    # Archived / superseded
    if layer in {"archive", "quarantine"} or status in {"archived", "superseded", "legacy", "scratch"}:
        return "archived"

    # Canonical
    if layer == "canonical" or status == "canonical" or auth == "canonical":
        return "canonical"

    # No epistemic state at all → raw/imported
    if d is None and q is None and c is None:
        return "raw_imported"

    # Expired valid_until
    if vuntil:
        try:
            exp = datetime.fromisoformat(vuntil.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(tz=timezone.utc):
                return "expired"
        except Exception:
            pass

    # Zero-mode states
    if d == 0 and m == "cancel":
        return "canceled"
    if d == 0 and m == "contain":
        return "contained"
    if d == 0:
        return "contained"  # unresolved zero — treat as contain

    # Approved threshold (low-cost tier)
    q_val = float(q) if q is not None else 0.0
    c_val = float(c) if c is not None else 0.0
    if q_val >= 0.65 and c_val >= 0.60 and correction in {None, "accurate", "incomplete"}:
        if status in {"approved", "canonical_candidate"} or auth == "approved":
            return "approved"

    # Has epistemic state but not meeting thresholds → under_review
    return "under_review"


# ── Custodian lane constants (ordered for display) ─────────────────────────────

CUSTODIAN_LANES = [
    "raw_imported",
    "expired",
    "canceled",
    "contained",
    "under_review",
    "approved",
    "canonical",
    "archived",
]

CUSTODIAN_LANE_X = {
    "raw_imported": 0.08,
    "expired":      0.21,
    "canceled":     0.34,
    "contained":    0.47,
    "under_review": 0.60,
    "approved":     0.73,
    "canonical":    0.86,
    "archived":     0.95,
}

CUSTODIAN_LANE_COLORS = {
    "raw_imported": "#475569",   # slate — neutral
    "expired":      "#6b7280",   # gray — faded
    "canceled":     "#ef4444",   # red — contradiction
    "contained":    "#f59e0b",   # amber — holding
    "under_review": "#60a5fa",   # blue — active review
    "approved":     "#34d399",   # green — cleared
    "canonical":    "#10b981",   # bright green — canonical center
    "archived":     "#334155",   # dark — archived memory
}

CUSTODIAN_LANE_BOUNDARIES = [0.145, 0.275, 0.405, 0.535, 0.665, 0.795, 0.905]


# ── Correction status colors ───────────────────────────────────────────────────

CORRECTION_STATUS_COLORS = {
    "accurate":        "#22c55e",
    "incomplete":      "#60a5fa",
    "outdated":        "#f59e0b",
    "conflicting":     "#f97316",
    "likely_incorrect": "#ef4444",
    None:              "#475569",
}

D_STATE_COLORS = {
    1:    "#22c55e",   # affirmed
    0:    "#f59e0b",   # unresolved
    -1:   "#ef4444",   # negated
    None: "#475569",   # no epistemic state
}

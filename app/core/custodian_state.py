"""Daenary Custodian State as mutation substrate.

Phase 24.4 hardening: queue status is not the source of truth. Canonical
mutation must first pass the Daenary state contract: d/m/q/c/valid_until/
context_ref/correction_status/canonical_lock.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DEFAULT_CUSTODIAN_STATE = {
    "d": 0,
    "m": "contain",
    "q": 0.0,
    "c": 0.0,
    "valid_until": None,
    "context_ref": None,
    "correction_status": "incomplete",
    "canonical_lock": False,
}

def _parse_dt(v: str | None):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None

def normalize_custodian_state(metadata: dict[str, Any] | None, *, context_ref: Any = None, valid_until: str | None = None) -> dict[str, Any]:
    metadata = metadata or {}
    raw = metadata.get("daenary_custodian_state") or metadata.get("custodian_state") or {}
    if not isinstance(raw, dict):
        raw = {}
    state = dict(DEFAULT_CUSTODIAN_STATE)
    state.update(raw)
    if state.get("valid_until") is None and valid_until:
        state["valid_until"] = valid_until
    if state.get("context_ref") is None and context_ref:
        state["context_ref"] = context_ref
    try:
        state["d"] = int(state.get("d")) if state.get("d") is not None else 0
    except Exception:
        state["d"] = 0
    state["m"] = state.get("m") or ("contain" if state["d"] == 0 else None)
    try:
        state["q"] = max(0.0, min(1.0, float(state.get("q") or 0.0)))
        state["c"] = max(0.0, min(1.0, float(state.get("c") or 0.0)))
    except Exception:
        state["q"], state["c"] = 0.0, 0.0
    state["correction_status"] = state.get("correction_status") or "incomplete"
    state["canonical_lock"] = bool(state.get("canonical_lock", False))
    return state

def custodian_mutation_gate(state: dict[str, Any], *, canonical_mutation: bool = True) -> dict[str, Any]:
    """Return whether Daenary state permits canonical mutation."""
    failures: list[str] = []
    if state.get("canonical_lock"):
        failures.append("canonical_lock")
    node_ref = state.get("context_ref")
    if node_ref:
        try:
            from app.db import connection as db
            row = db.fetchone("SELECT 1 FROM canonical_locks WHERE node_id=? AND active=1 LIMIT 1", (str(node_ref),))
            if row:
                failures.append("server_canonical_lock")
        except Exception:
            pass
    d = state.get("d")
    m = state.get("m")
    if d == 0 and m not in {"contain", "cancel"}:
        failures.append("zero_mode_missing")
    if m == "cancel":
        failures.append("contradiction_cancel_state")
    if state.get("correction_status") in {"conflicting", "likely_incorrect", "outdated"}:
        failures.append("correction_status_block")
    vu = _parse_dt(state.get("valid_until"))
    if state.get("valid_until") and vu and vu < datetime.now(timezone.utc):
        failures.append("expired_truth")
    if canonical_mutation and not state.get("context_ref"):
        failures.append("missing_context_ref")
    if canonical_mutation:
        if float(state.get("q") or 0.0) < 0.65:
            failures.append("low_measurement_quality")
        if float(state.get("c") or 0.0) < 0.60:
            failures.append("low_interpretation_confidence")
    return {
        "allowed": len(failures) == 0,
        "failures": failures,
        "state": state,
        "authority": "daenary_custodian_state",
    }

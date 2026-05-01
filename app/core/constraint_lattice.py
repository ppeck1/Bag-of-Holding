"""app/core/constraint_lattice.py: Constraint Lattice for Bag of Holding v2.

Phase 20: Establish the actual transition authority system.

Canonical Mutation Invariant:
  No node may transition d=0 → d=±1, or epistemic_state → canonical,
  without a valid certificate. No exceptions. No bypasses.

Four lattice rules, drawn from Daenary trinary state law and CANON constraint geometry:

  Rule A — Zero State Legitimacy
    d=0 is a valid, stable state. Not incomplete. Not failure.
    Active containment. System must not pressure forced resolution.

  Rule B — Forced Collapse Detection
    d=0 → ±1 without certificate is a collapse event. Must be logged.
    Matches E_rp(t) = 1 from the CANON collapse model.

  Rule C — Authority Alignment
    Mutation authority must match plane responsibility.
    Projection cannot certify canon. Viewer cannot certify governance.
    Wrong-plane authority = invalid certificate.

  Rule D — Expiry Decay
    Expired certificates invalidate promotion.
    No stale authority. Coherence decays. Refresh required.
    Matches C(t) = C₀e^(-kτ) + R(t).

Allowed scope (Phase 20):
  ✓ Constraint lattice transition gate
  ✓ Forced collapse detection and logging
  ✓ Authority alignment checking
  ✓ Expiry validation

Not in scope:
  ✗ LLM autonomous approval
  ✗ Automatic canonical promotion
  ✗ Projection-driven mutation
  ✗ Multi-user delegation
  ✗ Membrane security
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.db import connection as db

# ── Authority-plane contract ──────────────────────────────────────────────────
# Phase 20.1 uses explicit epistemic authority planes. These are not roles.
# They are declared certificate scope boundaries and are auditable.

VALID_AUTHORITY_PLANES: set[str] = {
    "verification",
    "governance",
    "evidence",
    "narrative",
    "operational",
    "constitutional",
}

INVALID_AUTHORITY_PLANES: set[str] = {
    "projection", "llm", "viewer", "admin", "automated", "system", "developer", "dev", "demo"
}


# Legacy rank map retained for Phase 20 tests and diagnostics. Phase 20.1
# enforcement uses VALID_AUTHORITY_PLANES + AUTHORITY_COMPATIBILITY above.
PLANE_RANK: dict[str, int] = {
    "Viewer": 0, "projection": 0, "llm": 0, "automated": 0,
    "Import": 1, "Internal": 2, "Archive": 2,
    "Evidence": 3, "Review": 4, "Governance": 5, "Canonical": 6,
    "viewer": 0, "evidence": 3, "governance": 5, "constitutional": 6,
}

# Minimum certificate authority plane required by transition.
# This is intentionally explicit rather than inferred from UI context.
TRANSITION_REQUIRED_AUTHORITY: dict[tuple[int | None, int], str] = {
    (0,   1):  "verification",
    (0,  -1):  "governance",
    (-1,  1):  "verification",
    (1,  -1):  "governance",
    (1,   0):  "governance",
    (-1,  0):  "governance",
    (None, 1): "verification",
    (None, 0): "verification",
    (None,-1): "governance",
}

AUTHORITY_COMPATIBILITY: dict[str, set[str]] = {
    "verification":   {"verification", "constitutional"},
    "evidence":       {"evidence", "verification", "constitutional"},
    "narrative":      {"narrative", "constitutional"},
    "operational":    {"operational", "governance", "constitutional"},
    "governance":     {"governance", "constitutional"},
    "constitutional": {"constitutional"},
}

def normalize_authority_plane(value: str | None) -> str:
    return (value or "").strip().lower()

def validate_authority_plane(authority_plane: str | None, required_plane: str | None = None) -> list[str]:
    plane = normalize_authority_plane(authority_plane)
    errors: list[str] = []
    if not plane:
        return ["authority_plane is required and must be declared, not inferred"]
    if plane in INVALID_AUTHORITY_PLANES or plane not in VALID_AUTHORITY_PLANES:
        return [f"invalid authority_plane {plane!r}; projection, llm, viewer, admin, dev, and demo are not authority planes"]
    if required_plane:
        req = normalize_authority_plane(required_plane)
        allowed = AUTHORITY_COMPATIBILITY.get(req, {req})
        if plane not in allowed:
            errors.append(f"authority_plane mismatch: {plane!r} cannot authorize {req!r} transition")
    return errors

# Target plane for each d-state transition
TRANSITION_TARGET_PLANE: dict[tuple[int | None, int], str] = {
    (0,   1):  "Evidence",    # contain → affirm
    (0,  -1):  "Governance",  # contain → negate (requires governance authority)
    (-1,  1):  "Governance",  # negate → affirm (contradiction resolution)
    (1,  -1):  "Governance",  # affirm → negate (serious reversal)
    (1,   0):  "Governance",  # affirm → contain (canonical reversion)
    (-1,  0):  "Governance",  # negate → contain (reversion)
    (None, 1): "Internal",    # unset → affirm
    (None, 0): "Internal",    # unset → contain
    (None,-1): "Governance",  # unset → negate
}

# Risk class per transition
TRANSITION_RISK: dict[tuple[int | None, int], str] = {
    (0,   1):  "moderate",
    (0,  -1):  "high",
    (-1,  1):  "high",
    (1,  -1):  "high",
    (1,   0):  "moderate",  # revert affirm→contain
    (-1,  0):  "moderate",  # revert negate→contain
    (None, 1): "low",
    (None, 0): "low",
    (None,-1): "moderate",
}

# Q/C thresholds by risk class
QC_THRESHOLDS: dict[str, dict[str, float]] = {
    "low":      {"min_q": 0.60, "min_c": 0.50},
    "moderate": {"min_q": 0.70, "min_c": 0.60},
    "high":     {"min_q": 0.85, "min_c": 0.75},
    "critical": {"min_q": 0.95, "min_c": 0.90},
}


# ── Lattice transition legality ────────────────────────────────────────────────

def check_transition_legal(
    from_d: int | None,
    to_d:   int | None,
    from_mode: str | None = None,
    to_mode:   str | None = None,
    certificate: dict | None = None,
    target_plane: str | None = None,
) -> dict[str, Any]:
    """Check whether a d-state transition is lattice-legal.

    Returns:
      {
        "legal": bool,
        "requires_certificate": bool,
        "risk_class": str,
        "reason": str,
        "errors": list[str],
        "forced_collapse": bool,
      }

    Rule A: d=0 is a valid stable state — not a failure requiring resolution.
    Rule B: d=0 → ±1 without certificate is a forced collapse (blocked + logged).
    Rule C: certificate authority_plane must match the required epistemic authority plane.
    Rule D: expired certificate blocks transition.
    """
    errors: list[str] = []
    forced_collapse  = False
    requires_cert    = True

    # Trivial identity transitions are always legal
    if from_d == to_d:
        return {
            "legal": True,
            "requires_certificate": False,
            "risk_class": "none",
            "reason": "Identity transition — no state change",
            "errors": [],
            "forced_collapse": False,
        }

    key = (from_d, to_d)
    risk_class = TRANSITION_RISK.get(key, "high")
    req_plane  = TRANSITION_REQUIRED_AUTHORITY.get(key, "governance")

    # Rule B: forced collapse check
    if from_d == 0 and to_d in {1, -1}:
        if certificate is None:
            forced_collapse = True
            errors.append(
                f"FORCED COLLAPSE: d=0→{to_d} without certificate. "
                f"Rule B violation — zero-state legitimacy requires explicit certificate."
            )
        # Note: even with a certificate, we still validate it below (Rules C, D)

    # Require certificate for all non-trivial transitions
    if certificate is None:
        errors.append(
            "Certificate required for state transition. "
            "Direct promotion is not permitted."
        )
        return {
            "legal": False,
            "requires_certificate": True,
            "risk_class": risk_class,
            "reason": errors[0],
            "errors": errors,
            "forced_collapse": forced_collapse,
        }

    # Rule C: explicit authority-plane alignment
    cert_plane = certificate.get("authority_plane") or certificate.get("plane_authority")
    for err in validate_authority_plane(cert_plane, req_plane):
        errors.append(f"Rule C violation: {err}")

    # Rule D: expiry check
    valid_until = certificate.get("valid_until") or ""
    if valid_until:
        try:
            exp = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(tz=timezone.utc):
                errors.append(
                    f"Rule D violation: certificate expired at {valid_until}. "
                    f"No stale authority — coherence decays."
                )
        except Exception:
            errors.append(f"Rule D: cannot parse valid_until {valid_until!r}")

    # Certificate status must be approved
    cert_status = certificate.get("status", "pending")
    if cert_status != "approved":
        errors.append(
            f"Certificate status is {cert_status!r} — only 'approved' certificates "
            f"may authorize state transitions."
        )

    # QC thresholds for the risk class
    thresholds = QC_THRESHOLDS.get(risk_class, QC_THRESHOLDS["high"])
    cert_q = float(certificate.get("q") or 0.0)
    cert_c = float(certificate.get("c") or 0.0)
    if cert_q < thresholds["min_q"]:
        errors.append(
            f"Certificate q={cert_q:.2f} below {risk_class}-risk threshold "
            f"(min_q={thresholds['min_q']})."
        )
    if cert_c < thresholds["min_c"]:
        errors.append(
            f"Certificate c={cert_c:.2f} below {risk_class}-risk threshold "
            f"(min_c={thresholds['min_c']})."
        )

    legal = len(errors) == 0
    return {
        "legal":                legal,
        "requires_certificate": True,
        "risk_class":           risk_class,
        "reason":               errors[0] if errors else "Transition is lattice-legal.",
        "errors":               errors,
        "forced_collapse":      forced_collapse and not legal,
    }


def get_risk_class(from_d: int | None, to_d: int | None) -> str:
    """Return the risk class for a given d-state transition."""
    return TRANSITION_RISK.get((from_d, to_d), "high")


def get_qc_thresholds(risk_class: str) -> dict[str, float]:
    """Return the q/c thresholds for a given risk class."""
    return QC_THRESHOLDS.get(risk_class, QC_THRESHOLDS["high"])


# ── Forced collapse detection ──────────────────────────────────────────────────

def is_forced_collapse(from_d: int | None, to_d: int, has_certificate: bool) -> bool:
    """Rule B: d=0 → ±1 without certificate is a forced collapse event."""
    return from_d == 0 and to_d in {1, -1} and not has_certificate


# ── Immutable lattice event log ────────────────────────────────────────────────

def log_lattice_event(
    event_type:     str,
    node_id:        str,
    from_d:         int | None = None,
    to_d:           int | None = None,
    from_mode:      str | None = None,
    to_mode:        str | None = None,
    reason:         str | None = None,
    certificate_id: str | None = None,
    severity:       str = "warning",
    detail:         dict | None = None,
) -> int:
    """Append an immutable lattice event. Never deletes. Never updates.

    Returns the row id of the new event.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    conn = db.get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO lattice_events
              (event_type, certificate_id, node_id, from_d, to_d,
               from_mode, to_mode, reason, detected_at, severity, detail_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_type, certificate_id, node_id,
                from_d, to_d, from_mode, to_mode,
                reason, now, severity,
                json.dumps(detail or {}),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        # Table may not exist in test/migration contexts — log is best-effort.
        # Never block application logic on audit logging.
        return -1
    finally:
        conn.close()


def get_lattice_events(node_id: str | None = None, limit: int = 100) -> list[dict]:
    """Query lattice events. Immutable — no update or delete path."""
    if node_id:
        rows = db.fetchall(
            "SELECT * FROM lattice_events WHERE node_id = ? ORDER BY id DESC LIMIT ?",
            (node_id, limit),
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM lattice_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in rows]


# ── Canonical promotion gate ───────────────────────────────────────────────────

CANONICAL_PROMOTION_PLANES = {"canonical", "canonical_candidate", "review_required"}

def can_apply_transition(
    doc: dict,
    to_d: int,
    certificate: dict | None,
) -> dict[str, Any]:
    """Lattice gate for applying a d-state transition to a document.

    Logs forced collapse events. Returns the legality verdict.
    This is the hard trust boundary for all canonical mutations.
    """
    from_d    = doc.get("epistemic_d")
    from_mode = doc.get("epistemic_m")
    node_id   = doc.get("doc_id") or doc.get("id") or ""

    result = check_transition_legal(
        from_d     = from_d,
        to_d       = to_d,
        from_mode  = from_mode,
        certificate= certificate,
    )

    # Rule B: log forced collapse
    if result.get("forced_collapse"):
        log_lattice_event(
            event_type     = "forced_collapse",
            node_id        = node_id,
            from_d         = from_d,
            to_d           = to_d,
            from_mode      = from_mode,
            reason         = result["reason"],
            certificate_id = (certificate or {}).get("certificate_id"),
            severity       = "critical",
            detail         = {"from_d": from_d, "to_d": to_d, "doc": node_id},
        )

    return result

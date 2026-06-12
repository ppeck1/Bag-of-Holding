"""app/core/sc3_constitutive.py: SC3 Constitutive Boundary Enforcement.

Phase 26C — Substrate Lattice Closure Decision.

The SC3³ lattice is not documentation.
It is not a parallel ontology.
It is infrastructure — but ONLY at constitutive boundaries.

Core Rule (Phase 26C Mandate):
    If substrate registration does not change behavior → it is documentation.
    If substrate registration changes constitutive boundaries → it is infrastructure.

This module implements the enforcement side of that rule.

Constitutive zones (SC3 must change behavior):
    - canonical promotion
    - authority resolution
    - custodianship transfer
    - scope legitimacy enforcement
    - temporal validity enforcement

Descriptive zones (SC3 provides orientation only):
    - drafts
    - notes
    - exploration branches
    - LLM synthesis
    - research scaffolding

Plane mismatch rule:
    Subjective-plane evidence CANNOT directly overwrite physical-plane canon.
    Any cross-plane canonical mutation requires custodian review.
    The system blocks, records the event, and names the required resolver.

SC3 Plane Hierarchy for promotion authority:
    physical > informational > subjective

    physical    — empirical, sensor data, measurement
    informational — structured knowledge, policy, codified facts
    subjective  — interpretation, inference, opinion, LLM synthesis

Phase 26C implementation provides:
    - sc3_constitutive_check()     — gate for any constitutive action
    - sc3_plane_hierarchy_check()  — specific plane mismatch detection
    - sc3_promotion_gate()         — canonical promotion plane enforcement
    - sc3_map_node_to_plane()      — infer SC3 plane from doc/node metadata
    - list_sc3_violations()        — audit trail of blocked constitutive attempts
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from app.db import connection as db
from app.core.audit import log_event

# ---------------------------------------------------------------------------
# Plane hierarchy
# ---------------------------------------------------------------------------

PLANE_HIERARCHY: dict[str, int] = {
    "physical": 3,       # highest epistemic authority
    "informational": 2,
    "subjective": 1,     # lowest epistemic authority (interpretation, LLM)
}

# SC3 coordinate prefix → plane
COORDINATE_TO_PLANE: dict[str, str] = {
    "K.P": "physical", "X.P": "physical", "F.P": "physical",
    "K.I": "informational", "X.I": "informational", "F.I": "informational",
    "K.S": "subjective", "X.S": "subjective", "F.S": "subjective",
    "CPL": "informational",   # coupling is informational by default
    "PROJ": "informational",  # projection operator
    "OBS": "informational",   # observation model
}

# Document plane indicators from metadata fields
_PLANE_INDICATORS: dict[str, str] = {
    # source_type → plane
    "sensor": "physical",
    "measurement": "physical",
    "observation": "physical",
    "physical_record": "physical",
    "canon_folder": "informational",
    "policy": "informational",
    "rule": "informational",
    "structured_knowledge": "informational",
    "llm_synthesis": "subjective",
    "inference": "subjective",
    "interpretation": "subjective",
    "opinion": "subjective",
    "draft": "subjective",
}

# Constitutive action types — SC3 enforcement is mandatory here
CONSTITUTIVE_ACTIONS: frozenset[str] = frozenset({
    "canonical_promotion",
    "authority_resolution",
    "custodianship_transfer",
    "scope_legitimacy",
    "temporal_enforcement",
    "canonical_lock",
    "governance_acceptance",
    "irreversible_acceptance",
})

# Descriptive action types — SC3 provides orientation only, no enforcement
DESCRIPTIVE_ACTIONS: frozenset[str] = frozenset({
    "draft_save",
    "note_create",
    "exploration_branch",
    "llm_synthesis",
    "speculative_mapping",
    "temporary_inference",
    "research_scaffolding",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _violation_id(action: str, node_id: str) -> str:
    raw = f"{action}|{node_id}|{time.time_ns()}".encode()
    return "SC3V_" + hashlib.sha1(raw).hexdigest()[:12]


def _json_loads(v: str | None, default: Any) -> Any:
    if not v:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Plane inference
# ---------------------------------------------------------------------------

def sc3_map_node_to_plane(metadata: dict[str, Any]) -> str:
    """Infer the SC3 epistemic plane for a node from its metadata.

    Priority:
        1. Explicit sc3_plane field in metadata
        2. Explicit plane_scope or plane_path field
        3. source_type mapping
        4. corpus_class / document_class heuristic
        5. Default: informational
    """
    if not metadata:
        return "informational"

    # Explicit sc3_plane wins
    explicit = str(metadata.get("sc3_plane") or "").strip().lower()
    if explicit in PLANE_HIERARCHY:
        return explicit

    # plane_scope (may be comma-separated)
    plane_scope = str(metadata.get("plane_scope") or metadata.get("plane_path") or "").strip().lower()
    for plane in ("physical", "subjective", "informational"):
        if plane in plane_scope:
            return plane

    # source_type mapping
    source_type = str(metadata.get("source_type") or "").strip().lower()
    if source_type in _PLANE_INDICATORS:
        return _PLANE_INDICATORS[source_type]

    # corpus_class / document_class heuristic
    corpus_class = str(
        metadata.get("corpus_class") or metadata.get("document_class") or ""
    ).strip().lower()
    if "physical" in corpus_class or "sensor" in corpus_class:
        return "physical"
    if "llm" in corpus_class or "synthetic" in corpus_class or "draft" in corpus_class:
        return "subjective"
    if "canon" in corpus_class or "policy" in corpus_class:
        return "informational"

    # Default
    return "informational"


# ---------------------------------------------------------------------------
# Constitutive boundary check
# ---------------------------------------------------------------------------

def sc3_constitutive_check(action: str) -> dict[str, Any]:
    """Return whether an action is constitutive (SC3-enforced) or descriptive (advisory).

    Constitutive: SC3 registration MUST change system behavior.
    Descriptive: SC3 registration provides orientation only.

    This is the architectural closure decision mandated by Phase 26C.
    """
    if action in CONSTITUTIVE_ACTIONS:
        return {
            "constitutive": True,
            "descriptive": False,
            "action": action,
            "sc3_enforcement": "mandatory",
            "message": (
                f"Action '{action}' is a constitutive boundary. "
                "SC3 substrate registration changes system behavior. "
                "Plane validation is enforced, not advisory."
            ),
        }
    if action in DESCRIPTIVE_ACTIONS:
        return {
            "constitutive": False,
            "descriptive": True,
            "action": action,
            "sc3_enforcement": "advisory",
            "message": (
                f"Action '{action}' is a descriptive zone. "
                "SC3 registration provides orientation only. "
                "No governance enforcement applied."
            ),
        }
    # Unknown action: treat as constitutive by default (conservative)
    return {
        "constitutive": True,
        "descriptive": False,
        "action": action,
        "sc3_enforcement": "mandatory_by_default",
        "message": (
            f"Action '{action}' is not explicitly classified. "
            "Defaulting to constitutive enforcement (conservative). "
            "Register action type to suppress."
        ),
    }


def sc3_plane_hierarchy_check(
    source_plane: str,
    target_plane: str,
    action: str = "canonical_promotion",
) -> dict[str, Any]:
    """Check whether a cross-plane mutation is permitted by the hierarchy.

    Rule: Lower-authority planes cannot directly overwrite higher-authority planes.
        subjective  → physical    : BLOCKED (requires custodian review)
        subjective  → informational: BLOCKED (requires custodian review)
        informational → physical  : BLOCKED (requires custodian review)
        Same plane                : ALLOWED (standard governance applies)
        Higher → lower            : ALLOWED (downgrade path, still needs approval)

    Returns: dict with allowed, mismatch, required_resolver, explanation
    """
    src_rank = PLANE_HIERARCHY.get(source_plane.lower(), 1)
    tgt_rank = PLANE_HIERARCHY.get(target_plane.lower(), 2)

    allowed = src_rank >= tgt_rank  # source must have >= authority than target
    mismatch = src_rank < tgt_rank

    if mismatch:
        # Determine required resolver based on severity
        if source_plane.lower() == "subjective" and target_plane.lower() == "physical":
            required_resolver = "Physical Canon Custodian"
            severity = "critical"
            explanation = (
                f"BLOCKED: Subjective-plane evidence cannot directly overwrite physical-plane canon. "
                f"Interpretation/inference attempting to mutate empirical record. "
                f"Required: {required_resolver}. Escalation path: Custodian review → forced escalation."
            )
        elif source_plane.lower() == "subjective" and target_plane.lower() == "informational":
            required_resolver = "Informational Canon Custodian"
            severity = "high"
            explanation = (
                f"BLOCKED: Subjective-plane evidence cannot directly overwrite informational canon. "
                f"LLM synthesis or interpretation cannot mutate structured knowledge without validation. "
                f"Required: {required_resolver}."
            )
        else:
            required_resolver = f"{target_plane.capitalize()} Canon Custodian"
            severity = "medium"
            explanation = (
                f"BLOCKED: Plane mismatch. '{source_plane}' evidence cannot directly overwrite "
                f"'{target_plane}' canon. Required: {required_resolver}."
            )
        return {
            "allowed": False,
            "mismatch": True,
            "source_plane": source_plane,
            "target_plane": target_plane,
            "source_rank": src_rank,
            "target_rank": tgt_rank,
            "required_resolver": required_resolver,
            "severity": severity,
            "action": action,
            "explanation": explanation,
            "next_path": f"Custodian resolution by {required_resolver} or forced escalation review.",
            "why_override_impossible": (
                "SC3 constitutive boundary. The plane hierarchy is structural, "
                "not advisory. Subjective inference cannot become physical truth "
                "without validation through the authority chain."
            ),
        }

    return {
        "allowed": True,
        "mismatch": False,
        "source_plane": source_plane,
        "target_plane": target_plane,
        "source_rank": src_rank,
        "target_rank": tgt_rank,
        "required_resolver": None,
        "severity": "none",
        "action": action,
        "explanation": (
            f"Plane check passed. '{source_plane}' has sufficient epistemic authority "
            f"for '{target_plane}' mutation."
        ),
    }


# ---------------------------------------------------------------------------
# Canonical promotion gate
# ---------------------------------------------------------------------------

def sc3_promotion_gate(
    doc_id: str,
    doc_metadata: dict[str, Any],
    target_state: str,
    requested_by: str,
    target_doc_id: str | None = None,
    target_doc_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """SC3 constitutive gate for canonical promotion.

    Blocks promotion if:
        1. Source document is subjective-plane and target canon is physical-plane.
        2. Source document is subjective-plane and target canon is informational-plane.
        3. Source is informational-plane and target is physical-plane.

    Always permitted (SC3 not a blocker):
        - Same-plane promotion (still requires normal governance)
        - Higher → lower plane (still requires normal governance)
        - Explicit SC3 custodian override in metadata

    Records the violation (or pass) permanently in the sc3_violations audit table.
    """
    db.init_db()
    source_plane = sc3_map_node_to_plane(doc_metadata)

    # Determine target plane:
    # If target_doc_metadata provided → use it
    # Otherwise infer from target_state (canonical → informational by default)
    if target_doc_metadata:
        target_plane = sc3_map_node_to_plane(target_doc_metadata)
    else:
        # Canonical state implies informational plane by default
        # Physical canon requires explicit physical plane registration
        target_plane = "informational"
        if "physical" in str(target_state).lower():
            target_plane = "physical"
        elif "subjective" in str(target_state).lower():
            target_plane = "subjective"

    constitutive = sc3_constitutive_check("canonical_promotion")
    if not constitutive["constitutive"]:
        # Should never reach here for canonical_promotion, but defensive
        return {
            "sc3_blocked": False,
            "sc3_pass": True,
            "source_plane": source_plane,
            "target_plane": target_plane,
            "reason": "action classified as descriptive (unexpected for canonical_promotion)",
        }

    plane_check = sc3_plane_hierarchy_check(source_plane, target_plane, "canonical_promotion")

    # Check for explicit SC3 custodian override
    custodian_override = bool(
        doc_metadata.get("sc3_custodian_override")
        or doc_metadata.get("sc3_override_approved_by")
    )

    if not plane_check["allowed"] and not custodian_override:
        # Record violation
        _record_sc3_violation(
            action="canonical_promotion",
            node_id=doc_id,
            source_plane=source_plane,
            target_plane=target_plane,
            requested_by=requested_by,
            plane_check=plane_check,
            metadata=doc_metadata,
        )
        return {
            "sc3_blocked": True,
            "sc3_pass": False,
            "source_plane": source_plane,
            "target_plane": target_plane,
            "plane_mismatch": True,
            "required_resolver": plane_check["required_resolver"],
            "severity": plane_check["severity"],
            "explanation": plane_check["explanation"],
            "next_path": plane_check["next_path"],
            "why_override_impossible": plane_check["why_override_impossible"],
            "doc_id": doc_id,
            "requested_by": requested_by,
            "target_state": target_state,
            "sc3_enforcement": "constitutive",
            "message": (
                "SC3 constitutive boundary enforcement blocked this promotion. "
                f"{plane_check['explanation']}"
            ),
        }

    return {
        "sc3_blocked": False,
        "sc3_pass": True,
        "source_plane": source_plane,
        "target_plane": target_plane,
        "plane_mismatch": False,
        "custodian_override": custodian_override,
        "explanation": plane_check["explanation"],
        "sc3_enforcement": "constitutive",
        "doc_id": doc_id,
        "requested_by": requested_by,
    }


# ---------------------------------------------------------------------------
# Violation audit
# ---------------------------------------------------------------------------

def _record_sc3_violation(
    action: str,
    node_id: str,
    source_plane: str,
    target_plane: str,
    requested_by: str,
    plane_check: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Permanently record a SC3 constitutive violation."""
    vid = _violation_id(action, node_id)
    try:
        db.execute(
            """INSERT OR IGNORE INTO sc3_violations
                 (violation_id, action, node_id, source_plane, target_plane,
                  requested_by, required_resolver, severity, explanation,
                  created_at, metadata_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                vid, action, node_id, source_plane, target_plane,
                requested_by,
                plane_check.get("required_resolver", ""),
                plane_check.get("severity", ""),
                plane_check.get("explanation", ""),
                _now_iso(),
                json.dumps({"plane_check": plane_check, "doc_metadata": metadata or {}}),
            ),
        )
    except Exception:
        pass
    try:
        log_event(
            "sc3_constitutive_violation",
            actor_type="system",
            actor_id=requested_by,
            detail=json.dumps({
                "action": action,
                "node_id": node_id,
                "source_plane": source_plane,
                "target_plane": target_plane,
                "required_resolver": plane_check.get("required_resolver"),
                "severity": plane_check.get("severity"),
            }),
        )
    except Exception:
        pass


def list_sc3_violations(
    action: str | None = None,
    node_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List SC3 constitutive violations."""
    db.init_db()
    _ensure_sc3_violations_table()
    q = "SELECT * FROM sc3_violations WHERE 1=1"
    params: list[Any] = []
    if action:
        q += " AND action=?"
        params.append(action)
    if node_id:
        q += " AND node_id=?"
        params.append(node_id)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.fetchall(q, tuple(params))
    out = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json_loads(d.get("metadata_json"), {})
        out.append(d)
    return out


def _ensure_sc3_violations_table() -> None:
    """Idempotent migration: create sc3_violations table if absent."""
    try:
        db.execute(
            """CREATE TABLE IF NOT EXISTS sc3_violations (
                violation_id  TEXT PRIMARY KEY,
                action        TEXT NOT NULL,
                node_id       TEXT NOT NULL,
                source_plane  TEXT NOT NULL,
                target_plane  TEXT NOT NULL,
                requested_by  TEXT NOT NULL,
                required_resolver TEXT NOT NULL,
                severity      TEXT NOT NULL,
                explanation   TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                metadata_json TEXT DEFAULT '{}'
            )"""
        )
    except Exception:
        pass


def sc3_mapping_summary() -> dict[str, Any]:
    """Return the full SC3 constitutive / descriptive mapping for external documentation."""
    return {
        "equation": "X_{t+1} = Pi_K(F(X_t))",
        "planes": {
            "physical": {"rank": 3, "description": "empirical, sensor data, measurement, observation"},
            "informational": {"rank": 2, "description": "structured knowledge, policy, codified facts"},
            "subjective": {"rank": 1, "description": "interpretation, inference, opinion, LLM synthesis"},
        },
        "plane_hierarchy_rule": (
            "Lower-authority planes cannot directly overwrite higher-authority planes. "
            "subjective → physical: BLOCKED. subjective → informational: BLOCKED. "
            "informational → physical: BLOCKED. Requires custodian resolution."
        ),
        "constitutive_zones": sorted(CONSTITUTIVE_ACTIONS),
        "descriptive_zones": sorted(DESCRIPTIVE_ACTIONS),
        "mutation_rules": {
            "canonical_promotion": "constitutive — SC3 plane check enforced",
            "authority_resolution": "constitutive — authority chain is SC3-validated",
            "custodianship_transfer": "constitutive — requires explicit promotion contract",
            "scope_legitimacy": "constitutive — scope mismatch blocked by SC3",
            "temporal_enforcement": "constitutive — expired validity blocked by SC3",
            "draft_save": "descriptive — SC3 provides orientation only",
            "llm_synthesis": "descriptive — subjective plane, no governance enforcement",
            "exploration_branch": "descriptive — fast path, no bureaucratic overhead",
        },
        "sc3_becomes_architecture_when": (
            "Substrate registration changes the outcome of a constitutive action. "
            "If SC3 plane metadata does NOT change whether a promotion is blocked, "
            "SC3 is still documentation. Phase 26C mandate: SC3 must change behavior "
            "at constitutive boundaries."
        ),
        "boh_mapping": {
            "SC3.K.*": "Constraint Geometry (governance rules, scope limits)",
            "SC3.X.*": "Daenary State (custodian state, canonical lock)",
            "SC3.F.*": "Escalation / Custodian Actions (authority transfer)",
            "SC3.OBS": "Integrity Panel (visibility surface, Atlas)",
            "SC3.PROJ": "Canonical Lock (projection operator — what is observable as canonical)",
        },
    }

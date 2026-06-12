"""app/core/translation.py: User-Facing Language Translation Layer.

Phase 26.1 — Authority-Legible Surface Without Architectural Renaming.

Core principle:
    Keep internal architecture names.
    Simplify only the user-facing operational surface.

    Internal:  Daenary, Rubrix, Atlas, Canonical, SC3, contained, cancelled
    UI label:  Confidence State, Review Center, Visualization, Trusted Source,
               Substrate, Held for Resolution, Contradiction Blocked

This module is the ONLY place that maps internal terms to user-facing labels.
It must be used by any route that surfaces labels directly to the user.
It must NEVER be used to rename internal architecture, DB columns, or API routes.

Conceptual distinctions preserved (must never be collapsed):
    Authority   — who may decide (legitimacy, causal, creates trust)
    Confidence  — how strong is the evidence (epistemic quality)
    Trust       — is this safe to rely on (derived outcome: authority + confidence)

Usage:
    from app.core.translation import user_label, translate_status, translate_mode
    from app.core.translation import TRANSLATION_TABLE, ZONE_LABELS, STATUS_LABELS

    label = user_label("Integrity Panel")        # → "Authority Center"
    label = translate_status("contained")        # → "Held for Resolution"
    label = translate_mode("constitutional")     # → "Authority Path"
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Canonical translation table — the authoritative mapping
# ---------------------------------------------------------------------------
# Internal Name           : User-Facing Name
# Only apply to UI labels. Never apply to internal architecture, routes, or schemas.

TRANSLATION_TABLE: dict[str, str] = {
    # Panels / navigation
    "Integrity Panel":      "Authority Center",
    "Daenary State":        "Confidence State",
    "Constitutional Mode":  "Authority Path",
    "Constraint Geometry":  "Risk Map",
    "Variable Overlay":     "Evidence State",
    "Review Queue":         "Resolution Center",
    "Suggested Changes":    "Proposed Changes",
    "Planes":               "Domains",

    # Status values
    "Canonical":            "Trusted Source",
    "Contained":            "Held for Resolution",
    "Cancelled":            "Contradiction Blocked",

    # Lowercased variants (internal API values)
    "canonical":            "Trusted Source",
    "contained":            "Held for Resolution",
    "cancelled":            "Contradiction Blocked",
    "canceled":             "Contradiction Blocked",    # alternate spelling used in some lanes
}

# Visualization mode → user-facing label
VIZ_MODE_LABELS: dict[str, str] = {
    "web":           "Web",
    "variable":      "Evidence State",
    "constraint":    "Risk Map",
    "constitutional": "Authority Path",
}

# Status → user-facing label (for status badges and display)
STATUS_LABELS: dict[str, str] = {
    "canonical":              "Trusted Source",
    "canonical_locked":       "Trusted Source (Locked)",
    "contained":              "Held for Resolution",
    "cancelled":              "Contradiction Blocked",
    "canceled":               "Contradiction Blocked",
    "draft":                  "Draft",
    "approved":               "Approved",
    "archived":               "Archived",
    "superseded":             "Superseded",
    "quarantine":             "Quarantine",
    "pending_review":         "Pending Review",
    "under_review":           "Under Review",
    "expired":                "Expired",
    "escalated":              "Escalated",
    "forced_escalation":      "Escalated — Authority Transferred",
    "locked":                 "Locked",
    "warning":                "Warning",
    "raw_imported":           "Imported",
    "blocked":                "Contradiction Blocked",
    "reverted":               "Reverted",
    "forced_collapse_detected": "Forced Collapse",
}

# Daenary m-state → user-facing Confidence State label
CONFIDENCE_STATE_LABELS: dict[str, str] = {
    "contain":     "Held for Resolution",
    "warn":        "Warning",
    "lock":        "Locked",
    "escalate":    "Escalated",
    "release":     "Released",
}

# Zone labels for governance/escalation states
ZONE_LABELS: dict[str, str] = {
    "warning":          "⚠️  Warning",
    "contain":          "🔒 Held for Resolution",
    "forced_escalation": "🚨 Authority Transferred",
    "locked":           "🔐 Locked",
    "resolved":         "✅ Resolved",
}

# Navigation panel labels
NAV_LABELS: dict[str, str] = {
    "integrity":      "Authority Center",
    "dashboard":      "Dashboard",
    "input":          "Inbox",
    "library":        "Library",
    "search":         "Search",
    "canon-conflicts": "Conflicts",
    "duplicates":     "Duplicates",
    "import-ingest":  "Bulk Import",
    "atlas":          "Visualization",
    "governance":     "Review Center",
    "llm-queue":      "Proposed Changes",
    "status":         "System Status",
    "planes":         "Domains",
}


# ---------------------------------------------------------------------------
# Translation functions
# ---------------------------------------------------------------------------

def user_label(internal_name: str, fallback: str | None = None) -> str:
    """Translate an internal name to its user-facing label.

    Does NOT rename internal architecture (Daenary, Rubrix, Atlas, SC3).
    Only translates the specific labels in TRANSLATION_TABLE.

    Args:
        internal_name: The internal name to translate.
        fallback: If not in table, return this. Defaults to internal_name.
    Returns:
        User-facing label string.
    """
    return TRANSLATION_TABLE.get(internal_name, fallback if fallback is not None else internal_name)


def translate_status(status: str) -> str:
    """Translate an internal status value to a user-facing label.

    Args:
        status: Internal status string (e.g., "canonical", "contained").
    Returns:
        User-facing status label.
    """
    return STATUS_LABELS.get(str(status or "").strip().lower(), status or "—")


def translate_mode(mode: str) -> str:
    """Translate a visualization mode key to its user-facing label.

    Args:
        mode: Internal mode key (e.g., "constitutional", "variable").
    Returns:
        User-facing mode label.
    """
    return VIZ_MODE_LABELS.get(str(mode or "").strip().lower(), mode or "—")


def translate_confidence_state(m_state: str) -> str:
    """Translate a Daenary m-state to its Confidence State user label.

    Internal engine: Daenary.
    User-facing name: Confidence State.
    """
    return CONFIDENCE_STATE_LABELS.get(str(m_state or "").strip().lower(), m_state or "—")


def translate_zone(zone: str) -> str:
    """Translate a governance zone/escalation state to a user-facing label."""
    return ZONE_LABELS.get(str(zone or "").strip().lower(), zone or "—")


def translate_nav(panel_id: str) -> str:
    """Translate a panel ID to its navigation label."""
    return NAV_LABELS.get(str(panel_id or "").strip().lower(), panel_id or "—")


def apply_translations(data: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Apply status translation to specified fields in a data dict.

    Adds a `*_label` key for each translated field (non-destructive).

    Example:
        apply_translations({"status": "contained"}, ["status"])
        → {"status": "contained", "status_label": "Held for Resolution"}
    """
    result = dict(data)
    for field in fields:
        if field in result:
            result[f"{field}_label"] = translate_status(str(result[field] or ""))
    return result


def legibility_passes_test(label: str) -> bool:
    """Check if a label passes the legibility test.

    Phase 26.1 test:
        Would a smart non-builder pause to decode this label?
        If yes → the label is wrong.

    Returns True if label is legible (no pause needed).
    Returns False if label is architecture-native and needs translation.
    """
    # Architecture-native terms that require translation
    _architecture_native = {
        "Integrity Panel", "integrity panel",
        "Daenary State", "daenary state", "Daenary substrate state",
        "Constitutional Mode", "constitutional mode",
        "Constraint Geometry", "constraint geometry",
        "Variable Overlay", "variable overlay",
        "Review Queue", "review queue",
        "Suggested Changes", "suggested changes",
        "Contained", "contained",
        "Cancelled", "cancelled", "Canceled", "canceled",
    }
    return label not in _architecture_native


def full_translation_map() -> dict[str, Any]:
    """Return the complete translation mapping for documentation/API."""
    return {
        "version": "26.1",
        "principle": (
            "Keep internal architecture names. "
            "Simplify only the user-facing operational surface. "
            "Do NOT rename Daenary, Rubrix, Atlas, Canonical, SC3 internally."
        ),
        "translation_table": TRANSLATION_TABLE,
        "viz_mode_labels": VIZ_MODE_LABELS,
        "status_labels": STATUS_LABELS,
        "confidence_state_labels": CONFIDENCE_STATE_LABELS,
        "zone_labels": ZONE_LABELS,
        "nav_labels": NAV_LABELS,
        "conceptual_distinctions": {
            "authority": "Who may decide? (legitimacy, causal, creates trust)",
            "confidence": "How strong is the evidence? (epistemic quality, not permission)",
            "trust": "Is this safe to rely on? (derived: legitimate authority + sufficient confidence)",
        },
        "language_model_rule": (
            "Lead with: authority, resolution, confidence, risk, trusted source. "
            "Not with: ontology, symbolism, internal framework names."
        ),
    }

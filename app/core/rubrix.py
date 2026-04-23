"""app/core/rubrix.py: Rubrix lifecycle ontology and validation for Bag of Holding v2.

Split from parser.py (v0P). Logic unchanged.
Contains: VALID_TYPES, VALID_STATUSES, OPERATOR_STATES, OPERATOR_INTENTS,
          ALLOWED_TRANSITIONS, validate_header()

Ontology label: RUBRIX_LIFECYCLE_v1
"""

# ── Ontology constants ──────────────────────────────────────────────────────
VALID_TYPES = {"note", "canon", "reference", "log", "event", "person", "ledger", "project"}

VALID_STATUSES = {"draft", "working", "canonical", "archived"}

OPERATOR_STATES = {"observe", "vessel", "constraint", "integrate", "release"}

OPERATOR_INTENTS = {
    "capture", "triage", "define", "extract",
    "reconcile", "refactor", "canonize", "archive"
}

ALLOWED_TRANSITIONS = {
    "observe": {"vessel"},
    "vessel": {"constraint"},
    "constraint": {"integrate"},
    "integrate": {"release"},
    "release": {"constraint"},  # patch only
}


def validate_header(boh: dict) -> list[str]:
    """Run all lint checks against a parsed boh header. Return list of errors.

    Logic unchanged from parser.py v0P validate_header().
    """
    errors: list[str] = []

    # Required fields
    for field in ("id", "type", "purpose", "status", "updated"):
        if field not in boh:
            errors.append(f"LINT_MISSING_FIELD: '{field}' is required.")

    doc_type = boh.get("type")
    status = boh.get("status")
    rubrix = boh.get("rubrix", {})
    op_state = rubrix.get("operator_state") if rubrix else None
    op_intent = rubrix.get("operator_intent") if rubrix else None

    # Type validation
    if doc_type and doc_type not in VALID_TYPES:
        errors.append(f"LINT_INVALID_TYPE: '{doc_type}' not in {VALID_TYPES}")

    # Status validation
    if status and status not in VALID_STATUSES:
        errors.append(f"LINT_INVALID_STATUS: '{status}' not in {VALID_STATUSES}")

    # Rubrix validation
    if not rubrix:
        errors.append("LINT_MISSING_RUBRIX: 'rubrix' block is required.")
    else:
        if op_state not in OPERATOR_STATES:
            errors.append(f"LINT_INVALID_OPERATOR_STATE: '{op_state}' not in {OPERATOR_STATES}")
        if op_intent not in OPERATOR_INTENTS:
            errors.append(f"LINT_INVALID_OPERATOR_INTENT: '{op_intent}' not in {OPERATOR_INTENTS}")

        # Hard constraints — PRESERVE (R6, R7, R8)
        if status == "canonical" and op_state != "release":
            errors.append(
                f"LINT_CONSTRAINT_VIOLATION: status=canonical requires operator_state=release, got '{op_state}'"
            )
        if doc_type == "canon" and op_state == "observe":
            errors.append(
                "LINT_CONSTRAINT_VIOLATION: type=canon cannot have operator_state=observe"
            )
        if status == "archived" and op_state != "release":
            errors.append(
                f"LINT_CONSTRAINT_VIOLATION: status=archived requires operator_state=release, got '{op_state}'"
            )

    # Updated timestamp
    from datetime import datetime
    updated = boh.get("updated")
    if updated:
        try:
            if isinstance(updated, str):
                datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"LINT_INVALID_DATE: 'updated' must be ISO8601, got '{updated}'")

    return errors

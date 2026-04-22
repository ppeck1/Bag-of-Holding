"""parser.py: Markdown header parser and Rubrix lifecycle validator for Bag of Holding v0P."""

import re
import hashlib
from datetime import datetime, timezone
from typing import Any

import yaml

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

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DEF_BLOCK_RE = re.compile(r"(?:^|\n)(?:#+\s+|>?\s*\*\*)?([A-Z][A-Za-z ]+):\s*\n((?:.+\n?)+?)(?=\n#+|\Z)", re.MULTILINE)


# ── Parsing ─────────────────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict | None, str, list[str]]:
    """Return (header_dict, body_text, lint_errors)."""
    errors: list[str] = []
    match = FRONTMATTER_RE.match(text)
    if not match:
        errors.append("LINT_MISSING_HEADER: No valid YAML frontmatter found.")
        return None, text, errors

    try:
        raw = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        errors.append(f"LINT_YAML_PARSE_ERROR: {e}")
        return None, text[match.end():], errors

    boh = raw.get("boh") if isinstance(raw, dict) else None
    if not boh:
        errors.append("LINT_MISSING_BOH_KEY: Frontmatter must contain 'boh:' root key.")
        return None, text[match.end():], errors

    body = text[match.end():]
    return boh, body, errors


def validate_header(boh: dict) -> list[str]:
    """Run all lint checks against a parsed boh header. Return list of errors."""
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

        # Hard constraints
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
    updated = boh.get("updated")
    if updated:
        try:
            if isinstance(updated, str):
                datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"LINT_INVALID_DATE: 'updated' must be ISO8601, got '{updated}'")

    return errors


def extract_definitions(body: str, plane_scope: list) -> list[dict]:
    """Extract definition blocks from document body."""
    defs = []
    # Look for patterns like "**Term**: definition" or "### Term\n..."
    term_re = re.compile(r"\*\*([A-Z][A-Za-z ]+)\*\*\s*[:\-]\s*(.+)", re.MULTILINE)
    heading_def_re = re.compile(r"^#{2,4}\s+([A-Z][A-Za-z ]+)\s*\n((?:.|\n)*?)(?=^#{1,4}|\Z)", re.MULTILINE)

    seen = set()
    for m in term_re.finditer(body):
        term = m.group(1).strip()
        block = m.group(0)
        bh = hashlib.sha256(block.encode()).hexdigest()[:16]
        if bh not in seen:
            seen.add(bh)
            defs.append({
                "term": term,
                "block_hash": bh,
                "block_text": block[:500],
                "plane_scope_json": str(plane_scope),
            })

    return defs


def extract_events(body: str) -> list[dict]:
    """Extract explicit Event blocks from document body."""
    events = []
    event_block_re = re.compile(
        r"## Event:\s*\n((?:\s*-[^\n]+\n?)+)", re.MULTILINE
    )
    for m in event_block_re.finditer(body):
        block = m.group(1)
        ev: dict[str, Any] = {}
        for line in block.splitlines():
            line = line.strip().lstrip("- ")
            if ":" in line:
                k, _, v = line.partition(":")
                ev[k.strip().lower()] = v.strip()
        if "start" in ev:
            events.append(ev)
    return events


def parse_iso_to_epoch(dt_str: str | None) -> int | None:
    if not dt_str:
        return None
    try:
        if isinstance(dt_str, datetime):
            return int(dt_str.replace(tzinfo=timezone.utc).timestamp())
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


def parse_semver(version: str | None) -> int:
    """Return sortable integer from semver string. Higher = newer."""
    if not version:
        return 0
    parts = str(version).lstrip("v").split(".")
    try:
        major, minor, patch = (int(p) for p in (parts + ["0", "0", "0"])[:3])
        return major * 1_000_000 + minor * 1_000 + patch
    except ValueError:
        return 0

"""app/services/parser.py: Markdown parsing and extraction utilities for Bag of Holding v2.

Split from parser.py (v0P). Logic unchanged.
Contains: parse_frontmatter, extract_definitions, extract_events,
          parse_iso_to_epoch, parse_semver

Ontology label: BOH_CANON_v3.7
"""

import re
import hashlib
from datetime import datetime, timezone
from typing import Any

import yaml

# Regex patterns — unchanged from v0P
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DEF_BLOCK_RE = re.compile(
    r"(?:^|\n)(?:#+\s+|>?\s*\*\*)?([A-Z][A-Za-z ]+):\s*\n((?:.+\n?)+?)(?=\n#+|\Z)",
    re.MULTILINE,
)


def parse_frontmatter(text: str) -> tuple[dict | None, str, list[str]]:
    """Return (header_dict, body_text, lint_errors). Logic unchanged from v0P."""
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


def parse_frontmatter_full(text: str) -> tuple[dict | None, dict, str, list[str]]:
    """Extended parser that preserves the full raw YAML header.

    Phase 8 addition. Backward-compatible — callers that only need the boh subtree
    continue to use parse_frontmatter().

    Returns:
        boh        — the required 'boh:' subtree (or None if missing/invalid)
        raw_header — full parsed YAML dict including optional 'daenary:', etc.
        body       — markdown body with frontmatter stripped
        lint_errors — list of lint warning/error codes
    """
    errors: list[str] = []
    match = FRONTMATTER_RE.match(text)
    if not match:
        errors.append("LINT_MISSING_HEADER: No valid YAML frontmatter found.")
        return None, {}, text, errors

    try:
        raw = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        errors.append(f"LINT_YAML_PARSE_ERROR: {e}")
        return None, {}, text[match.end():], errors

    if not isinstance(raw, dict):
        errors.append("LINT_YAML_NOT_DICT: Frontmatter must be a YAML mapping.")
        return None, {}, text[match.end():], errors

    boh = raw.get("boh")
    if not boh:
        errors.append("LINT_MISSING_BOH_KEY: Frontmatter must contain 'boh:' root key.")
        return None, raw, text[match.end():], errors

    body = text[match.end():]
    return boh, raw, body, errors


def extract_definitions(body: str, plane_scope: list) -> list[dict]:
    """Extract definition blocks from document body. Logic unchanged from v0P."""
    defs = []
    term_re = re.compile(r"\*\*([A-Z][A-Za-z ]+)\*\*\s*[:\-]\s*(.+)", re.MULTILINE)

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
    """Extract explicit Event blocks from document body. Logic unchanged from v0P."""
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
    """Parse ISO 8601 string to Unix epoch int. Logic unchanged from v0P."""
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
    """Return sortable integer from semver string. Higher = newer. Logic unchanged from v0P.

    Formula: major × 1_000_000 + minor × 1_000 + patch
    (See math_authority.md §7)
    """
    if not version:
        return 0
    parts = str(version).lstrip("v").split(".")
    try:
        major, minor, patch = (int(p) for p in (parts + ["0", "0", "0"])[:3])
        return major * 1_000_000 + minor * 1_000 + patch
    except ValueError:
        return 0

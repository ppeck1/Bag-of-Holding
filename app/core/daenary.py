"""app/core/daenary.py: Daenary semantic state layer for Bag of Holding v2.

Phase 8 addition. Additive — does not replace Rubrix.

Daenary encodes epistemic / semantic state on documents as named dimensions:
    state      : -1 (negative) | 0 (unresolved) | +1 (positive)
    quality    : float [0,1]   — signal quality
    confidence : float [0,1]   — certainty of the encoding
    mode       : 'contain' | 'cancel'  — only valid when state == 0
    observed_at / valid_until : ISO timestamps

Design constraints:
    - Rubrix = lifecycle / governance state (unchanged)
    - Daenary = epistemic / semantic state (additive)
    - No auto-resolution: coordinates are observations, not decisions
    - Anti-collapse invariant: state 0 is never flipped to ±1 automatically
"""

import time
from typing import Any

from app.services.parser import parse_iso_to_epoch

VALID_STATES  = {-1, 0, 1}
VALID_MODES   = {"contain", "cancel"}
PERMEABILITY_DEFAULTS = {
    "duplicate_content": 0.95,
    "supersedes":        0.90,
    "canon_relates_to":  0.75,
    "derives":           0.80,
    "conflicts":         0.40,
}


# ── Validation ────────────────────────────────────────────────────────────────

def validate_dimension(dim: dict) -> list[str]:
    """Return list of lint warning codes for a single Daenary dimension dict."""
    warnings: list[str] = []

    if not isinstance(dim.get("name"), str) or not dim["name"].strip():
        warnings.append("LINT_INVALID_DAENARY_NAME")

    state = dim.get("state")
    if state not in VALID_STATES:
        warnings.append("LINT_INVALID_DAENARY_STATE")

    for field in ("quality", "confidence"):
        val = dim.get(field)
        if val is not None:
            try:
                fval = float(val)
                if not (0.0 <= fval <= 1.0):
                    warnings.append(f"LINT_INVALID_DAENARY_{field.upper()}")
            except (TypeError, ValueError):
                warnings.append(f"LINT_INVALID_DAENARY_{field.upper()}")

    mode = dim.get("mode")
    if mode is not None:
        if state != 0:
            warnings.append("LINT_INVALID_DAENARY_MODE")
        elif mode not in VALID_MODES:
            warnings.append("LINT_INVALID_DAENARY_MODE")

    for ts_field in ("observed_at", "valid_until"):
        val = dim.get(ts_field)
        if val is not None and parse_iso_to_epoch(str(val)) is None:
            warnings.append("LINT_INVALID_DAENARY_TIMESTAMP")

    return warnings


def validate_daenary_block(daenary: Any) -> list[str]:
    """Validate full daenary: block. Returns list of lint warning codes.
    Malformed individual dimensions produce warnings but do not block indexing.
    """
    if daenary is None:
        return []
    if not isinstance(daenary, dict):
        return ["LINT_INVALID_DAENARY_BLOCK"]

    dimensions = daenary.get("dimensions")
    if dimensions is None:
        return []
    if not isinstance(dimensions, list):
        return ["LINT_INVALID_DAENARY_DIMENSIONS"]

    warnings: list[str] = []
    for i, dim in enumerate(dimensions):
        if not isinstance(dim, dict):
            warnings.append(f"LINT_INVALID_DAENARY_DIMENSION_{i}")
            continue
        warnings.extend(validate_dimension(dim))
    return warnings


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_dimension(dim: dict) -> dict | None:
    """Normalize a single dimension dict to a storable form.
    Returns None if the dimension is too malformed to store (missing name or invalid state).
    """
    name = dim.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    state = dim.get("state")
    if state not in VALID_STATES:
        return None

    quality = None
    try:
        q = dim.get("quality")
        if q is not None:
            fq = float(q)
            quality = max(0.0, min(1.0, fq))
    except (TypeError, ValueError):
        pass

    confidence = None
    try:
        c = dim.get("confidence")
        if c is not None:
            fc = float(c)
            confidence = max(0.0, min(1.0, fc))
    except (TypeError, ValueError):
        pass

    mode = None
    if state == 0:
        m = dim.get("mode")
        if m in VALID_MODES:
            mode = m

    observed_ts    = parse_iso_to_epoch(str(dim["observed_at"])) if dim.get("observed_at") else None
    valid_until_ts = parse_iso_to_epoch(str(dim["valid_until"])) if dim.get("valid_until") else None

    return {
        "dimension":       name.strip().lower(),
        "state":           int(state),
        "quality":         quality,
        "confidence":      confidence,
        "mode":            mode,
        "observed_ts":     observed_ts,
        "valid_until_ts":  valid_until_ts,
        "source":          "frontmatter",
    }


def extract_coordinates(daenary: Any) -> tuple[list[dict], list[str]]:
    """Extract and normalize storable coordinates from a daenary: block.

    Returns:
        (coords, lint_warnings)
        coords — list of normalized coordinate dicts ready for DB insert
        lint_warnings — non-fatal lint codes for malformed entries
    """
    if not daenary or not isinstance(daenary, dict):
        return [], []

    dimensions = daenary.get("dimensions")
    if not dimensions or not isinstance(dimensions, list):
        return [], []

    coords: list[dict] = []
    warnings = validate_daenary_block(daenary)

    for dim in dimensions:
        if not isinstance(dim, dict):
            continue
        normalized = normalize_dimension(dim)
        if normalized is not None:
            coords.append(normalized)
        # else: malformed — skip row, lint warning already captured above

    return coords, warnings


# ── Persistence helpers ───────────────────────────────────────────────────────

def upsert_coordinates(conn, doc_id: str, coords: list[dict]):
    """Delete old coordinates for doc_id and insert fresh normalized rows."""
    conn.execute("DELETE FROM doc_coordinates WHERE doc_id = ?", (doc_id,))
    for c in coords:
        conn.execute(
            """
            INSERT INTO doc_coordinates
                (doc_id, dimension, state, quality, confidence, mode,
                 observed_ts, valid_until_ts, source)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                doc_id,
                c["dimension"],
                c["state"],
                c["quality"],
                c["confidence"],
                c["mode"],
                c["observed_ts"],
                c["valid_until_ts"],
                c["source"],
            ),
        )


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_coordinates(doc_id: str) -> list[dict]:
    """Return all coordinate rows for a given doc_id."""
    from app.db import connection as db
    return db.fetchall(
        "SELECT * FROM doc_coordinates WHERE doc_id = ? ORDER BY dimension",
        (doc_id,),
    )


def is_stale(coord: dict) -> bool:
    """Return True if coordinate has a valid_until_ts in the past."""
    vut = coord.get("valid_until_ts")
    if not vut:
        return False
    return int(time.time()) > vut


def format_coordinate_summary(coords: list[dict]) -> str:
    """Human-readable summary string for search result cards.
    Example: 'relevance=0(q0.80/c0.30 contain) · canon_alignment=+1(q0.90/c0.85)'
    """
    parts = []
    for c in coords:
        state_str = f"+{c['state']}" if c['state'] == 1 else str(c['state'])
        detail = ""
        if c.get("quality") is not None or c.get("confidence") is not None:
            q = f"q{c['quality']:.2f}" if c.get("quality") is not None else ""
            conf = f"c{c['confidence']:.2f}" if c.get("confidence") is not None else ""
            inner = "/".join(filter(None, [q, conf]))
            if c.get("mode"):
                inner = f"{inner} {c['mode']}" if inner else c["mode"]
            detail = f"({inner})" if inner else ""
        stale_flag = "⚠stale" if is_stale(c) else ""
        parts.append(f"{c['dimension']}={state_str}{detail}{' ' + stale_flag if stale_flag else ''}")
    return " · ".join(parts)

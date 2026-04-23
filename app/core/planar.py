"""app/core/planar.py: Planar math (Plane/Field/Node) storage and alignment scoring.

Moved from planar.py (v0P). Logic unchanged.

Ontology label: BOH_CANON_v3.7
All formulas: See docs/math_authority.md §5, §6.
"""

import time
import uuid
from typing import Optional

from app.db import connection as db


VALID_D = {-1, 0, 1}


def validate_fact(fact: dict) -> list[str]:
    """Validate a planar fact dict. Returns list of error strings."""
    errors = []
    d = fact.get("d")
    q = fact.get("q")
    c = fact.get("c")
    m = fact.get("m")
    plane_path = fact.get("plane_path")

    if not plane_path:
        errors.append("plane_path is required")
    if d not in VALID_D:
        errors.append(f"d must be -1, 0, or +1; got {d!r}")
    if q is None or not (0 <= float(q) <= 1):
        errors.append(f"q must be in [0,1]; got {q!r}")
    if c is None or not (0 <= float(c) <= 1):
        errors.append(f"c must be in [0,1]; got {c!r}")
    if d == 0 and m not in ("cancel", "contain"):
        errors.append(f"m must be 'cancel' or 'contain' when d=0; got {m!r}")
    return errors


def store_fact(
    plane_path: str,
    r: float,
    d: int,
    q: float,
    c: float,
    context_ref: str = "",
    m: Optional[str] = None,
    valid_until: Optional[int] = None,
    subject_id: Optional[str] = None,
) -> dict:
    """Validate and store a planar fact. Returns stored=True or stored=False+errors."""
    fact = {"plane_path": plane_path, "d": d, "q": q, "c": c, "m": m}
    errors = validate_fact(fact)
    if errors:
        return {"stored": False, "errors": errors}

    subject_id = subject_id or str(uuid.uuid4())
    ts = int(time.time())

    db.execute(
        """
        INSERT INTO plane_facts
          (subject_id, plane_path, r, d, q, c, m, ts, valid_until, context_ref)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (subject_id, plane_path, r, d, q, c, m, ts, valid_until, context_ref),
    )
    return {"stored": True, "subject_id": subject_id, "ts": ts}


def get_facts(plane_path: str) -> list[dict]:
    """Retrieve all active (non-expired) facts for a plane_path."""
    now = int(time.time())
    return db.fetchall(
        """
        SELECT * FROM plane_facts
        WHERE plane_path = ?
          AND (valid_until IS NULL OR valid_until > ?)
        ORDER BY ts DESC
        """,
        (plane_path, now),
    )


def planar_alignment_score(plane_scopes: list[str], query_plane: Optional[str] = None) -> float:
    """Compute planar alignment score for a document given its plane_scopes.

    Formula (math_authority.md §5):
        weight(f)    = q * c
        direction(f) = (d + 1) / 2.0  → -1:0.0, 0:0.5, +1:1.0
        score        = Σ(weight * direction) / Σ(weight)
        no facts     → 0.5 (neutral)
        empty scopes → 0.0

    Returns value in [0.0, 1.0].
    """
    if not plane_scopes:
        return 0.0

    now = int(time.time())
    total_weight = 0.0
    weighted_score = 0.0

    paths = plane_scopes[:]
    if query_plane and query_plane not in paths:
        paths.append(query_plane)

    rows = db.fetchall(
        f"""
        SELECT * FROM plane_facts
        WHERE plane_path IN ({','.join('?' * len(paths))})
          AND (valid_until IS NULL OR valid_until > ?)
        """,
        tuple(paths) + (now,),
    )

    for row in rows:
        weight = row["q"] * row["c"]
        direction = row["d"]
        normalized = (direction + 1) / 2.0  # -1→0, 0→0.5, +1→1
        weighted_score += weight * normalized
        total_weight += weight

    if total_weight == 0:
        return 0.5  # neutral if no facts

    return min(1.0, weighted_score / total_weight)

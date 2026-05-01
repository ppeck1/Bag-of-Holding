"""app/core/plane_card.py: PCDS Plane Card storage for Bag of Holding v2.

Phase 19: Make the BOH storage unit a Plane Card, not a document with metadata.

The PCDS (Plane-Centric Data System) object hierarchy:
  Plane          — a namespace / abstraction layer
  Card           — minimal data unit with deterministic header + payload
  Header         — Daenary-like metadata: b, d, m, delta, constraints, validity, context_ref
  Constraint Lattice — allowed transitions (added in Phase 20)
  Interface      — cross-plane translation artifacts (added in Phase 21)
  Certificate    — proof for base flips (added in Phase 20)

This module wraps existing documents as PlaneCards WITHOUT replacing content
storage. The cards table is a projection / view of the epistemic state of each
document in the governed memory substrate.

Invariants:
  - Every indexed document SHOULD have exactly one PlaneCard
  - A PlaneCard's epistemic fields mirror the doc's epistemic_* columns
  - The card's plane is derived deterministically from canonical_layer/status
  - card_type is derived from document_class/type
  - payload is a lightweight summary; full content stays in docs + filesystem
  - Cards are updated when documents are re-indexed (upsert by doc_id)
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any

from app.db import connection as db

# ── Plane derivation ───────────────────────────────────────────────────────────

PLANE_MAP = {
    "canonical":  "Canonical",
    "supporting": "Internal",
    "evidence":   "Evidence",
    "review":     "Review",
    "conflict":   "Conflict",
    "archive":    "Archive",
    "quarantine": "Archive",
}

CARD_TYPE_MAP = {
    "formal_system": "claim",
    "architecture":  "claim",
    "whitepaper":    "claim",
    "evidence":      "evidence",
    "source":        "evidence",
    "review":        "review",
    "review_artifact": "review",
    "reference":     "reference",
    "note":          "observation",
    "log":           "observation",
    "import":        "import",
    "legacy":        "import",
    "unknown":       "observation",
}

CORRECTION_STATUS_CERT_REQUIRED = {"conflicting", "likely_incorrect"}


def _derive_plane(doc: dict) -> str:
    """Derive PCDS plane from doc canonical_layer and status."""
    layer  = (doc.get("canonical_layer") or "").lower()
    status = (doc.get("status") or "").lower()
    if layer in PLANE_MAP: return PLANE_MAP[layer]
    if status == "canonical":  return "Canonical"
    if status in {"archived", "superseded", "legacy", "scratch"}: return "Archive"
    if status in {"conflict"}:  return "Conflict"
    if status in {"review_required", "review_artifact"}: return "Review"
    return "Internal"


def _derive_card_type(doc: dict) -> str:
    """Derive PCDS card_type from document_class and type."""
    dc = (doc.get("document_class") or doc.get("type") or "").lower()
    return CARD_TYPE_MAP.get(dc, "observation")


def _derive_constraints(doc: dict) -> dict:
    """Derive constraint lattice metadata from epistemic state."""
    correction = doc.get("epistemic_correction_status") or ""
    d = doc.get("epistemic_d")
    return {
        "context": f"C:{_derive_plane(doc)}:Standard",
        "requires_certificate_for_base_flip": True,
        "zero_containment": d == 0,
        "correction_status": correction or None,
        "allows_refinement": correction not in CORRECTION_STATUS_CERT_REQUIRED,
    }


def _derive_authority(doc: dict) -> dict:
    """Derive authority envelope from authority_state."""
    auth = (doc.get("authority_state") or "non_authoritative").lower()
    if auth == "canonical":
        return {"write": [], "resolve": ["custodian"], "locked": True}
    if auth == "approved":
        return {"write": ["user"], "resolve": ["user", "custodian"], "locked": False}
    return {"write": ["user"], "resolve": ["user"], "locked": False}


def _card_id(doc_id: str) -> str:
    """Generate a stable, deterministic card ID for a document."""
    h = hashlib.md5(doc_id.encode()).hexdigest()[:8]
    return f"CARD:{doc_id[:8]}:{h}"


def _iso(ts_epoch: int | None) -> str | None:
    if ts_epoch is None: return None
    try:
        return datetime.fromtimestamp(int(ts_epoch), tz=timezone.utc).isoformat()
    except Exception:
        return None


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class PlaneCard:
    """PCDS Plane Card — the canonical storage unit for a governed memory item.

    Header fields follow the PCDS spec. Payload is a lightweight projection of
    the source document's content (title, summary, path, topics).
    """
    id:               str
    plane:            str
    card_type:        str
    topic:            str
    b:                int                  = 0
    d:                int | None           = None
    m:                str | None           = None
    delta:            dict                 = field(default_factory=dict)
    constraints:      dict                 = field(default_factory=dict)
    authority:        dict                 = field(default_factory=dict)
    observed_at:      str | None           = None
    valid_until:      str | None           = None
    context_ref:      dict                 = field(default_factory=dict)
    payload:          dict                 = field(default_factory=dict)
    doc_id:           str | None           = None
    created_ts:       int | None           = None
    updated_ts:       int | None           = None
    plane_card_version: int                = 1

    def to_dict(self) -> dict:
        return asdict(self)


# ── Card creation from document ───────────────────────────────────────────────

def wrap_document_as_card(doc: dict) -> PlaneCard:
    """Build a PlaneCard from an existing document dict (from docs table).

    This is a non-destructive wrap: the source document is unchanged.
    The card mirrors the document's epistemic state in PCDS format.
    """
    doc_id  = doc.get("doc_id") or doc.get("id") or ""
    plane   = _derive_plane(doc)
    ctype   = _derive_card_type(doc)
    topic   = (doc.get("title") or doc.get("topics_tokens") or doc_id)[:120]
    ts_now  = int(time.time())

    return PlaneCard(
        id         = _card_id(doc_id),
        plane      = plane,
        card_type  = ctype,
        topic      = topic,
        b          = 0,
        d          = doc.get("epistemic_d"),
        m          = doc.get("epistemic_m"),
        delta      = {
            "kind":  "scalar",
            "dims":  [],
            "value": [],
        },
        constraints = _derive_constraints(doc),
        authority   = _derive_authority(doc),
        observed_at = _iso(doc.get("updated_ts")),
        valid_until = doc.get("epistemic_valid_until"),
        context_ref = {
            "source_id": f"DOC:boh:{doc_id}",
            "span":      None,
            "project":   doc.get("project"),
            "path":      doc.get("path"),
        },
        payload = {
            "title":        doc.get("title") or "",
            "summary":      (doc.get("summary") or "")[:220],
            "path":         doc.get("path") or "",
            "topics":       doc.get("topics_tokens") or "",
            "project":      doc.get("project") or "",
            "status":       doc.get("status") or "",
            "canonical_layer": doc.get("canonical_layer") or "",
            "epistemic_q":  doc.get("epistemic_q"),
            "epistemic_c":  doc.get("epistemic_c"),
            "correction_status": doc.get("epistemic_correction_status"),
            "custodian_lane": doc.get("custodian_review_state"),
        },
        doc_id      = doc_id,
        created_ts  = ts_now,
        updated_ts  = ts_now,
    )


# ── DB persistence ─────────────────────────────────────────────────────────────

def upsert_card(card: PlaneCard) -> None:
    """Insert or replace a PlaneCard in the cards table."""
    db.execute(
        """
        INSERT OR REPLACE INTO cards
          (id, plane, card_type, topic, b, d, m,
           delta_json, constraints_json, authority_json,
           observed_at, valid_until, context_ref_json, payload_json,
           doc_id, created_ts, updated_ts, plane_card_version)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            card.id, card.plane, card.card_type, card.topic,
            card.b, card.d, card.m,
            json.dumps(card.delta), json.dumps(card.constraints), json.dumps(card.authority),
            card.observed_at, card.valid_until,
            json.dumps(card.context_ref), json.dumps(card.payload),
            card.doc_id, card.created_ts, card.updated_ts, card.plane_card_version,
        ),
    )


def wrap_and_persist(doc: dict) -> PlaneCard:
    """Wrap document as PlaneCard and persist to DB. Called by indexer."""
    card = wrap_document_as_card(doc)
    upsert_card(card)
    return card


# ── DB retrieval ───────────────────────────────────────────────────────────────

def _row_to_card(row: dict) -> PlaneCard:
    """Deserialize a DB row into a PlaneCard."""
    def _j(s: str | None, default: Any = None) -> Any:
        if not s: return default if default is not None else {}
        try: return json.loads(s)
        except Exception: return default if default is not None else {}

    return PlaneCard(
        id          = row["id"],
        plane       = row["plane"],
        card_type   = row["card_type"],
        topic       = row["topic"] or "",
        b           = row.get("b") or 0,
        d           = row.get("d"),
        m           = row.get("m"),
        delta       = _j(row.get("delta_json"), {}),
        constraints = _j(row.get("constraints_json"), {}),
        authority   = _j(row.get("authority_json"), {}),
        observed_at = row.get("observed_at"),
        valid_until = row.get("valid_until"),
        context_ref = _j(row.get("context_ref_json"), {}),
        payload     = _j(row.get("payload_json"), {}),
        doc_id      = row.get("doc_id"),
        created_ts  = row.get("created_ts"),
        updated_ts  = row.get("updated_ts"),
        plane_card_version = row.get("plane_card_version") or 1,
    )


def get_card(card_id: str) -> PlaneCard | None:
    """Retrieve a PlaneCard by its CARD:... id."""
    row = db.fetchone("SELECT * FROM cards WHERE id = ?", (card_id,))
    return _row_to_card(row) if row else None


def get_card_for_doc(doc_id: str) -> PlaneCard | None:
    """Retrieve the PlaneCard wrapping a document."""
    row = db.fetchone("SELECT * FROM cards WHERE doc_id = ?", (doc_id,))
    if row: return _row_to_card(row)
    # Auto-wrap if missing
    doc = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc: return None
    card = wrap_document_as_card(dict(doc))
    upsert_card(card)
    return card


def list_cards(
    plane: str | None = None,
    card_type: str | None = None,
    d: int | None = None,
    m: str | None = None,
    q_min: float | None = None,
    c_min: float | None = None,
    valid_now: bool = False,
    expired: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[PlaneCard]:
    """List PlaneCards with optional filters. Phase 19 retrieval foundation."""
    q = "SELECT c.* FROM cards c"
    params: list = []

    joins: list[str] = []
    wheres: list[str] = []

    # q_min / c_min require joining docs table
    if q_min is not None or c_min is not None:
        joins.append("JOIN docs d ON c.doc_id = d.doc_id")
        if q_min is not None:
            wheres.append("d.epistemic_q >= ?")
            params.append(q_min)
        if c_min is not None:
            wheres.append("d.epistemic_c >= ?")
            params.append(c_min)

    if joins: q += " " + " ".join(joins)

    if plane:     wheres.append("c.plane = ?");     params.append(plane)
    if card_type: wheres.append("c.card_type = ?"); params.append(card_type)
    if d is not None: wheres.append("c.d = ?");     params.append(d)
    if m:         wheres.append("c.m = ?");         params.append(m)

    if valid_now:
        wheres.append("(c.valid_until IS NULL OR c.valid_until >= date('now'))")
    if expired:
        wheres.append("c.valid_until IS NOT NULL AND c.valid_until < date('now')")

    if wheres: q += " WHERE " + " AND ".join(wheres)
    q += " ORDER BY c.updated_ts DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    rows = db.fetchall(q, tuple(params))
    return [_row_to_card(r) for r in rows]


def list_planes() -> list[dict]:
    """List all distinct planes with card counts."""
    rows = db.fetchall(
        "SELECT plane, COUNT(*) as count, "
        "SUM(CASE WHEN d=1 THEN 1 ELSE 0 END) as affirmed, "
        "SUM(CASE WHEN d=0 THEN 1 ELSE 0 END) as unresolved, "
        "SUM(CASE WHEN d=-1 THEN 1 ELSE 0 END) as negated, "
        "SUM(CASE WHEN m='cancel' THEN 1 ELSE 0 END) as canceled, "
        "SUM(CASE WHEN m='contain' THEN 1 ELSE 0 END) as contained "
        "FROM cards GROUP BY plane ORDER BY plane"
    )
    return [dict(r) for r in rows]


def backfill_all_docs() -> dict:
    """Wrap all existing documents as PlaneCards. Called on startup / migration."""
    docs = db.fetchall("SELECT * FROM docs")
    created = updated = errors = 0
    for doc in docs:
        try:
            existing = db.fetchone("SELECT id FROM cards WHERE doc_id = ?", (doc["doc_id"],))
            card = wrap_document_as_card(dict(doc))
            upsert_card(card)
            if existing: updated += 1
            else:        created += 1
        except Exception:
            errors += 1
    return {"created": created, "updated": updated, "errors": errors, "total": len(docs)}

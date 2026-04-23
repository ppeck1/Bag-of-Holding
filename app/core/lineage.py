"""app/core/lineage.py: Lineage tracking and duplicate detection for Bag of Holding v2.

Implements docs/corpus_migration_doctrine.md §2 (duplicate handling) and §4 (lineage).

Duplicate handling principle: Link, never delete.
  - Identity duplicates (same doc_id): INSERT OR REPLACE handles; no lineage needed.
  - Content duplicates (same text_hash): both preserved, lineage link created.
  - Semantic near-duplicates: handled by conflict detection (canon_collision).

Relationship types stored in lineage table:
  duplicate_content  — same text_hash, different doc_id
  snapshot_source    — snapshot doc derived from a filesystem doc
  supersedes         — newer version of a doc (same topics + plane_scope, higher semver)
  derived_from       — LLM review artifact derived from source doc
"""

import time
from app.db import connection as db


RELATIONSHIP_TYPES = {
    "duplicate_content",
    "snapshot_source",
    "supersedes",
    "derived_from",
}


def record_link(doc_id: str, related_doc_id: str, relationship: str, detail: str = "") -> int | None:
    """Record a lineage link between two documents.

    Idempotent — does not insert if same (doc_id, related_doc_id, relationship) exists.
    Returns the lineage row id, or None if already existed.
    """
    if relationship not in RELATIONSHIP_TYPES:
        raise ValueError(f"Unknown relationship: {relationship!r}. Must be one of {RELATIONSHIP_TYPES}")

    existing = db.fetchone(
        "SELECT id FROM lineage WHERE doc_id=? AND related_doc_id=? AND relationship=?",
        (doc_id, related_doc_id, relationship),
    )
    if existing:
        return None

    db.execute(
        "INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail) "
        "VALUES (?,?,?,?,?)",
        (doc_id, related_doc_id, relationship, int(time.time()), detail or ""),
    )
    row = db.fetchone(
        "SELECT id FROM lineage WHERE doc_id=? AND related_doc_id=? AND relationship=?",
        (doc_id, related_doc_id, relationship),
    )
    return row["id"] if row else None


def get_lineage(doc_id: str) -> dict:
    """Return all lineage links for a document (both as source and as related)."""
    outbound = db.fetchall(
        "SELECT * FROM lineage WHERE doc_id = ? ORDER BY detected_ts DESC",
        (doc_id,),
    )
    inbound = db.fetchall(
        "SELECT * FROM lineage WHERE related_doc_id = ? ORDER BY detected_ts DESC",
        (doc_id,),
    )
    return {
        "doc_id": doc_id,
        "outbound": outbound,   # this doc is the source
        "inbound": inbound,     # this doc is the related target
        "total": len(outbound) + len(inbound),
    }


def find_content_duplicates(text_hash: str, exclude_doc_id: str = "") -> list[dict]:
    """Find all docs sharing the same text_hash (content duplicates).

    Returns list of matching doc rows (excluding exclude_doc_id if given).
    """
    if exclude_doc_id:
        return db.fetchall(
            "SELECT doc_id, path, status, source_type FROM docs WHERE text_hash = ? AND doc_id != ?",
            (text_hash, exclude_doc_id),
        )
    return db.fetchall(
        "SELECT doc_id, path, status, source_type FROM docs WHERE text_hash = ?",
        (text_hash,),
    )


def detect_and_record_content_duplicates(doc_id: str, text_hash: str) -> list[dict]:
    """Check for content duplicates of a newly indexed doc and record lineage links.

    Called by indexer after storing a doc.
    Returns list of duplicate records found (may be empty).
    """
    if not text_hash:
        return []

    duplicates = find_content_duplicates(text_hash, exclude_doc_id=doc_id)
    new_links = []
    for dup in duplicates:
        link_id = record_link(
            doc_id=doc_id,
            related_doc_id=dup["doc_id"],
            relationship="duplicate_content",
            detail=f"text_hash={text_hash[:16]}",
        )
        if link_id is not None:
            new_links.append({
                "duplicate_doc_id": dup["doc_id"],
                "duplicate_path": dup["path"],
                "lineage_id": link_id,
            })
    return new_links


def detect_supersession(doc_id: str, doc: dict) -> list[dict]:
    """Detect if this doc supersedes older versions of the same logical document.

    Criteria: same topics_tokens (non-empty) + same plane_scope_json + higher semver.
    Only fires when the new doc has status=canonical or working.
    """
    from app.services.parser import parse_semver

    topics = (doc.get("topics_tokens") or "").strip()
    plane  = doc.get("plane_scope_json") or "[]"
    status = doc.get("status") or ""

    if not topics or status not in ("canonical", "working"):
        return []

    new_rank = parse_semver(doc.get("version"))
    if new_rank == 0:
        return []

    candidates = db.fetchall(
        "SELECT doc_id, version, status FROM docs "
        "WHERE topics_tokens = ? AND plane_scope_json = ? AND doc_id != ?",
        (topics, plane, doc_id),
    )

    links = []
    for cand in candidates:
        old_rank = parse_semver(cand.get("version"))
        if new_rank > old_rank:
            link_id = record_link(
                doc_id=doc_id,
                related_doc_id=cand["doc_id"],
                relationship="supersedes",
                detail=f"v{doc.get('version')} > v{cand.get('version')}",
            )
            if link_id is not None:
                links.append({"superseded_doc_id": cand["doc_id"], "lineage_id": link_id})
    return links


def get_all_lineage(limit: int = 200) -> list[dict]:
    """Return all lineage records, most recent first."""
    return db.fetchall(
        "SELECT * FROM lineage ORDER BY detected_ts DESC LIMIT ?",
        (limit,),
    )

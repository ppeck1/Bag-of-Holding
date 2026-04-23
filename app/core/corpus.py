"""app/core/corpus.py: Corpus class assignment for Bag of Holding v2.

Implements the five corpus classes defined in docs/corpus_migration_doctrine.md §1.
Classification is deterministic — same inputs always produce same class.
No inference. No probability. No LLM involvement.

Classes:
  CORPUS_CLASS:CANON    — status=canonical, operator_state=release, no open conflicts
  CORPUS_CLASS:DRAFT    — status in {draft, working}, observe/vessel/constraint/integrate
  CORPUS_CLASS:DERIVED  — source_type=snapshot or llm_extract, or *.review.json
  CORPUS_CLASS:ARCHIVE  — status=archived, operator_state=release
  CORPUS_CLASS:EVIDENCE — type in {log, event}, or pure capture with no topics/defs
"""

from app.db import connection as db

# Class constants — match docs/corpus_migration_doctrine.md §1 exactly
CLASS_CANON    = "CORPUS_CLASS:CANON"
CLASS_DRAFT    = "CORPUS_CLASS:DRAFT"
CLASS_DERIVED  = "CORPUS_CLASS:DERIVED"
CLASS_ARCHIVE  = "CORPUS_CLASS:ARCHIVE"
CLASS_EVIDENCE = "CORPUS_CLASS:EVIDENCE"

DERIVED_SOURCE_TYPES = {"snapshot", "worker_export", "llm_extract", "derived"}


def classify(doc: dict) -> str:
    """Assign a corpus class to a document dict.

    Evaluated in priority order per corpus_migration_doctrine.md §1.
    Returns one of the five CORPUS_CLASS:* constants.
    """
    status       = doc.get("status") or ""
    op_state     = doc.get("operator_state") or ""
    source_type  = doc.get("source_type") or ""
    doc_type     = doc.get("type") or ""
    topics_tokens = doc.get("topics_tokens") or ""

    # 1. Derived — source_type indicates external/non-filesystem origin
    if source_type in DERIVED_SOURCE_TYPES:
        return CLASS_DERIVED

    # 2. Archive — must check before Canon since archived cannot be canonical (Rubrix constraint)
    if status == "archived" and op_state == "release":
        return CLASS_ARCHIVE

    # 3. Canon — canonical + release (conflict check handled at write time, not here)
    if status == "canonical" and op_state == "release":
        return CLASS_CANON

    # 4. Evidence — log/event types, or zero promotable structure
    if doc_type in {"log", "event"}:
        return CLASS_EVIDENCE
    if not topics_tokens.strip() and doc_type not in {"note","canon","reference","project","person","ledger"}:
        return CLASS_EVIDENCE

    # 5. Draft — everything else in active lifecycle
    return CLASS_DRAFT


def classify_and_update(doc_id: str, doc: dict) -> str:
    """Classify a document and write the result to docs.corpus_class."""
    cls = classify(doc)
    db.execute(
        "UPDATE docs SET corpus_class = ? WHERE doc_id = ?",
        (cls, doc_id),
    )
    return cls


def bulk_reclassify() -> dict:
    """Reclassify all documents in the DB. Used after migration or full re-index.

    Returns counts per class.
    """
    docs = db.fetchall("SELECT * FROM docs")
    counts: dict[str, int] = {}
    conn = db.get_conn()
    try:
        for doc in docs:
            cls = classify(doc)
            conn.execute(
                "UPDATE docs SET corpus_class = ? WHERE doc_id = ?",
                (cls, doc["doc_id"]),
            )
            counts[cls] = counts.get(cls, 0) + 1
        conn.commit()
    finally:
        conn.close()
    return counts


def get_class_distribution() -> dict:
    """Return count of docs per corpus class."""
    rows = db.fetchall(
        "SELECT corpus_class, COUNT(*) as count FROM docs GROUP BY corpus_class ORDER BY count DESC"
    )
    return {r["corpus_class"]: r["count"] for r in rows}

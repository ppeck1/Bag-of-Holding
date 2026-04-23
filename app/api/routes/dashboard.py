"""app/api/routes/dashboard.py: Dashboard stats endpoint for Bag of Holding v2.

Phase 4: Added corpus class distribution and lineage record count.
"""

from fastapi import APIRouter
from app.db import connection as db
from app.core.corpus import get_class_distribution

router = APIRouter(prefix="/api")


@router.get("/dashboard", summary="Knowledge base health summary")
def dashboard():
    """Returns counts and status summary for the Dashboard panel."""
    # Document counts by status
    doc_counts = db.fetchall("SELECT status, COUNT(*) as count FROM docs GROUP BY status")
    status_map = {r["status"]: r["count"] for r in doc_counts}

    total_docs      = sum(status_map.values())
    canonical_docs  = status_map.get("canonical", 0)
    draft_docs      = status_map.get("draft", 0)
    working_docs    = status_map.get("working", 0)
    archived_docs   = status_map.get("archived", 0)

    # Corpus class distribution (Phase 4)
    corpus_dist = get_class_distribution()

    # Conflict counts
    conflict_counts = db.fetchall(
        "SELECT acknowledged, COUNT(*) as count FROM conflicts GROUP BY acknowledged"
    )
    conflict_map        = {r["acknowledged"]: r["count"] for r in conflict_counts}
    open_conflicts      = conflict_map.get(0, 0)
    acknowledged_conflicts = conflict_map.get(1, 0)

    # Event count
    event_row = db.fetchone("SELECT COUNT(*) as count FROM events")
    total_events = event_row["count"] if event_row else 0

    # Indexed planes
    plane_row = db.fetchone("SELECT COUNT(DISTINCT plane_path) as count FROM plane_facts")
    indexed_planes = plane_row["count"] if plane_row else 0

    # Last indexed timestamp
    last_row = db.fetchone("SELECT MAX(updated_ts) as ts FROM docs")
    last_indexed_ts = last_row["ts"] if last_row else None

    # Docs with issues
    lint_row = db.fetchone("SELECT COUNT(*) as count FROM docs WHERE status IS NULL")
    docs_with_issues = lint_row["count"] if lint_row else 0

    # Lineage records (Phase 4)
    lineage_row = db.fetchone("SELECT COUNT(*) as count FROM lineage")
    lineage_records = lineage_row["count"] if lineage_row else 0

    # Duplicate count (Phase 4)
    dup_row = db.fetchone(
        "SELECT COUNT(*) as count FROM lineage WHERE relationship='duplicate_content'"
    )
    duplicate_links = dup_row["count"] if dup_row else 0

    return {
        "total_docs": total_docs,
        "canonical_docs": canonical_docs,
        "draft_docs": draft_docs,
        "working_docs": working_docs,
        "archived_docs": archived_docs,
        "docs_with_issues": docs_with_issues,
        "open_conflicts": open_conflicts,
        "acknowledged_conflicts": acknowledged_conflicts,
        "total_conflicts": open_conflicts + acknowledged_conflicts,
        "total_events": total_events,
        "indexed_planes": indexed_planes,
        "last_indexed_ts": last_indexed_ts,
        "corpus_class_distribution": corpus_dist,
        "lineage_records": lineage_records,
        "duplicate_links": duplicate_links,
    }

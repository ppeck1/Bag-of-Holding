"""app/api/routes/dashboard.py: Dashboard stats endpoint for Bag of Holding v2.

Phase 4: Added corpus class distribution and lineage record count.
"""

from typing import Optional
from fastapi import APIRouter, Query
from app.db import connection as db
from app.core.corpus import get_class_distribution

router = APIRouter(prefix="/api")


@router.get("/dashboard", summary="Knowledge base health summary")
def dashboard(project: Optional[str] = Query(None)):
    """Returns counts and status summary for the Dashboard panel.

    Phase 26.6: project parameter filters all epistemic counts by project.
    Also returns full projects list for the filter dropdown.
    """
    # Project filter clause
    where = ""
    params: tuple = ()
    if project:
        where = "WHERE project = ?"
        params = (project,)

    # Document counts by status
    doc_counts = db.fetchall(f"SELECT status, COUNT(*) as count FROM docs {where} GROUP BY status", params)
    status_map = {r["status"]: r["count"] for r in doc_counts}

    total_docs      = sum(status_map.values())
    canonical_docs  = status_map.get("canonical", 0)
    draft_docs      = status_map.get("draft", 0)
    working_docs    = status_map.get("working", 0)
    archived_docs   = status_map.get("archived", 0)

    # All available projects for the dropdown
    proj_rows = db.fetchall("SELECT DISTINCT project FROM docs WHERE project IS NOT NULL ORDER BY project")
    projects_list = [r["project"] for r in proj_rows if r["project"]]

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

    # Phase 18: Epistemic health counts
    ep_d_rows = db.fetchall(
        f"SELECT epistemic_d, COUNT(*) as count FROM docs {where} GROUP BY epistemic_d",
        params,
    )
    ep_d = {str(r["epistemic_d"]): r["count"] for r in ep_d_rows}

    ep_m_where = f"WHERE epistemic_m IS NOT NULL{' AND project = ?' if project else ''}"
    ep_m_params = (project,) if project else ()
    ep_m_rows = db.fetchall(
        f"SELECT epistemic_m, COUNT(*) as count FROM docs {ep_m_where} GROUP BY epistemic_m",
        ep_m_params,
    )
    ep_m = {r["epistemic_m"]: r["count"] for r in ep_m_rows}

    ep_no_state_extra = f" AND project = ?" if project else ""
    ep_no_state_row = db.fetchone(
        f"SELECT COUNT(*) as count FROM docs WHERE epistemic_d IS NULL AND epistemic_q IS NULL{ep_no_state_extra}",
        (project,) if project else (),
    )
    ep_no_state = ep_no_state_row["count"] if ep_no_state_row else 0

    ep_exp_extra = f" AND project = ?" if project else ""
    ep_expired_row = db.fetchone(
        f"SELECT COUNT(*) as count FROM docs WHERE epistemic_valid_until IS NOT NULL AND epistemic_valid_until < date('now'){ep_exp_extra}",
        (project,) if project else (),
    )
    ep_expired = ep_expired_row["count"] if ep_expired_row else 0

    # Custodian lane breakdown
    cust_where = f"WHERE custodian_review_state IS NOT NULL{' AND project = ?' if project else ''}"
    cust_params = (project,) if project else ()
    cust_rows = db.fetchall(
        f"SELECT custodian_review_state, COUNT(*) as count FROM docs {cust_where} GROUP BY custodian_review_state",
        cust_params,
    )
    custodian_lanes = {r["custodian_review_state"]: r["count"] for r in cust_rows}

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
        # Phase 18
        "epistemic_d_counts": ep_d,
        "epistemic_m_counts": ep_m,
        "epistemic_no_state": ep_no_state,
        "epistemic_expired": ep_expired,
        "custodian_lanes": custodian_lanes,
        # Phase 26.6: project filter support
        "projects": projects_list,
        "project_filter": project or None,
    }

"""app/api/routes/lineage.py: Lineage and corpus class endpoints for Bag of Holding v2.

New in Phase 4. All read-only except POST /api/lineage (manual link creation).
"""

from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from app.core import lineage as lineage_engine
from app.core.corpus import bulk_reclassify, get_class_distribution
from app.db import connection as db
from app.core.auth import require_operator
from app.core import actor_ledger as al
from app.core.fs_boundary import PathBoundaryViolation, get_library_root, resolve_under_library

router = APIRouter(prefix="/api")


# ── Lineage ───────────────────────────────────────────────────────────────────

@router.get("/lineage/{doc_id}", summary="Get all lineage links for a document")
def get_lineage(doc_id: str):
    doc = db.fetchone("SELECT doc_id FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return lineage_engine.get_lineage(doc_id)


@router.get("/lineage", summary="List all lineage records")
def list_lineage(
    limit: int = Query(100, ge=1, le=500),
    relationship: Optional[str] = Query(None, description="Filter by relationship type"),
):
    rows = lineage_engine.get_all_lineage(limit=limit)
    if relationship:
        rows = [r for r in rows if r["relationship"] == relationship]
    return {
        "count": len(rows),
        "relationship_filter": relationship,
        "valid_relationships": sorted(lineage_engine.RELATIONSHIP_TYPES),
        "lineage": rows,
    }


class ManualLinkRequest(BaseModel):
    doc_id: str
    related_doc_id: str
    relationship: str
    detail: Optional[str] = ""


@router.post("/lineage", summary="Manually record a lineage link between two documents")
def create_lineage_link(req: ManualLinkRequest, _operator: str = Depends(require_operator),
                        x_boh_actor_id: Optional[str] = Header(default=None, alias="X-BOH-Actor-ID")):
    """Create an explicit lineage link. Idempotent — duplicate links are not recorded twice."""
    for did in (req.doc_id, req.related_doc_id):
        if not db.fetchone("SELECT doc_id FROM docs WHERE doc_id = ?", (did,)):
            raise HTTPException(status_code=404, detail=f"Document {did} not found")
    try:
        link_id = lineage_engine.record_link(
            req.doc_id, req.related_doc_id, req.relationship, req.detail or ""
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if link_id is None:
        return {"created": False, "note": "Link already exists", "doc_id": req.doc_id,
                "related_doc_id": req.related_doc_id, "relationship": req.relationship}
    al.ledger_event("create_lineage", "document", req.doc_id,
                    actor_id=al.actor_from_env_or_header(x_boh_actor_id),
                    authority_result="allowed", authority_basis="operator_token_fallback",
                    after={"lineage_id": link_id, "related_doc_id": req.related_doc_id, "relationship": req.relationship},
                    source_route="/api/lineage")
    return {"created": True, "lineage_id": link_id, "doc_id": req.doc_id,
            "related_doc_id": req.related_doc_id, "relationship": req.relationship}


# ── Corpus class ──────────────────────────────────────────────────────────────

@router.get("/corpus/classes", summary="Get corpus class distribution")
def corpus_class_distribution():
    """Returns count of documents per corpus class."""
    dist = get_class_distribution()
    total = sum(dist.values())
    return {
        "total": total,
        "distribution": dist,
        "classes": [
            "CORPUS_CLASS:CANON",
            "CORPUS_CLASS:DRAFT",
            "CORPUS_CLASS:DERIVED",
            "CORPUS_CLASS:ARCHIVE",
            "CORPUS_CLASS:EVIDENCE",
        ],
    }


@router.post("/corpus/reclassify", summary="Reclassify all documents (re-run classifier over entire DB)")
def reclassify_all(_operator: str = Depends(require_operator)):
    """Re-run corpus class assignment over all documents in the DB.

    Deterministic — same inputs always produce the same class.
    Safe to run at any time. Does not modify content or scores.
    """
    counts = bulk_reclassify()
    return {
        "reclassified": sum(counts.values()),
        "distribution": counts,
    }


# ── Duplicates ────────────────────────────────────────────────────────────────

@router.get("/duplicates", summary="List all content duplicate lineage records")
def list_duplicates():
    """Returns all lineage records with relationship=duplicate_content."""
    rows = db.fetchall(
        "SELECT l.*, d1.path as doc_path, d2.path as related_path "
        "FROM lineage l "
        "LEFT JOIN docs d1 ON l.doc_id = d1.doc_id "
        "LEFT JOIN docs d2 ON l.related_doc_id = d2.doc_id "
        "WHERE l.relationship = 'duplicate_content' "
        "ORDER BY l.detected_ts DESC"
    )
    return {"count": len(rows), "duplicates": rows}


# ── Migration report ──────────────────────────────────────────────────────────

@router.post("/corpus/migration-report",
             summary="Generate corpus migration report (writes docs/migration_report.md)")
def run_migration_report(output_path: Optional[str] = Query("reports/migration_report.md"),
                         _operator: str = Depends(require_operator)):
    """Generate a full corpus migration report and write it to disk.
    Returns the report summary dict.
    """
    from app.services.migration_report import generate_migration_report
    try:
        safe_output = resolve_under_library(output_path or "reports/migration_report.md", get_library_root())
    except PathBoundaryViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return generate_migration_report(output_path=str(safe_output))


@router.get("/corpus/migration-report",
            summary="Get migration report summary from current DB state (does not write file)")
def get_migration_summary():
    """Return a quick summary of corpus health without writing a file."""
    from app.core.corpus import get_class_distribution
    dist = get_class_distribution()
    open_c = db.fetchone("SELECT COUNT(*) as n FROM conflicts WHERE acknowledged=0")
    ack_c  = db.fetchone("SELECT COUNT(*) as n FROM conflicts WHERE acknowledged=1")
    lin_c  = db.fetchone("SELECT COUNT(*) as n FROM lineage")
    schema = db.fetchall("SELECT version, applied_ts FROM schema_version ORDER BY applied_ts")
    return {
        "corpus_class_distribution": dist,
        "open_conflicts": open_c["n"] if open_c else 0,
        "acknowledged_conflicts": ack_c["n"] if ack_c else 0,
        "lineage_records": lin_c["n"] if lin_c else 0,
        "schema_versions": [r["version"] for r in schema],
    }


class DuplicateDecision(BaseModel):
    doc_id: str
    related_doc_id: str
    decision: str
    note: Optional[str] = ""


@router.post("/duplicates/decision", summary="Record a duplicate review decision")
def record_duplicate_decision(req: DuplicateDecision, _operator: str = Depends(require_operator),
                              x_boh_actor_id: Optional[str] = Header(default=None, alias="X-BOH-Actor-ID")):
    """Persist a duplicate disposition without deleting files.

    Decisions are review metadata only. Bag of Holding never removes source files.
    """
    allowed = {"canonical", "duplicate", "ignored", "quarantine"}
    if req.decision not in allowed:
        raise HTTPException(status_code=400, detail=f"decision must be one of {sorted(allowed)}")
    # WO-2 mutation isolation (gate-independent): duplicate dispositions update docs rows.
    from app.core import promoted_exposure
    if (promoted_exposure.is_promoted_doc_id(req.doc_id)
            or promoted_exposure.is_promoted_doc_id(req.related_doc_id)):
        raise HTTPException(status_code=409, detail=promoted_exposure.MUTATION_BLOCK_REASON)
    import time
    conn = db.get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS duplicate_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL,
                related_doc_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                note TEXT DEFAULT '',
                reviewer TEXT DEFAULT 'local_user',
                reviewed_ts INTEGER NOT NULL
            )
        """)
        ts = int(time.time())
        conn.execute(
            "INSERT INTO duplicate_reviews (doc_id, related_doc_id, decision, note, reviewed_ts) VALUES (?, ?, ?, ?, ?)",
            (req.doc_id, req.related_doc_id, req.decision, req.note or '', ts),
        )
        if req.decision == "quarantine":
            conn.execute(
                "UPDATE docs SET canonical_layer='quarantine', authority_state='quarantined', review_state='duplicate_review' WHERE doc_id IN (?, ?)",
                (req.doc_id, req.related_doc_id),
            )
        conn.commit()
        al.ledger_event("duplicate_decision", "document", req.doc_id,
                        actor_id=al.actor_from_env_or_header(x_boh_actor_id),
                        authority_result="allowed", authority_basis="operator_token_fallback",
                        after={"related_doc_id": req.related_doc_id, "decision": req.decision, "note": req.note},
                        source_route="/api/duplicates/decision")
        return {"ok": True, "decision": req.decision, "reviewed_ts": ts, "deletes_files": False}
    finally:
        conn.close()

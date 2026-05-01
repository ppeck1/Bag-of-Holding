"""app/api/routes/input_routes.py: Browser intake endpoints for Bag of Holding v2.

Phase 11 addition.

  POST /api/input/markdown  — create a Markdown note from the browser
  POST /api/input/upload    — upload one or more files
  GET  /api/input/recent    — recent browser-created/imported docs (from audit log)
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import input_surface

router = APIRouter(prefix="/api/input", tags=["input"])


class MarkdownNoteRequest(BaseModel):
    title:         str = "Untitled note"
    body:          str = ""
    topics:        list[str] = []
    target_folder: str = "scratch"


@router.post("/markdown", summary="Create a Markdown note from the browser")
def create_markdown_note(req: MarkdownNoteRequest):
    """Save a browser-created Markdown note into the managed library.

    Safety guarantees:
      - Title slugified; filename sanitized
      - Path constrained to library root (no traversal)
      - File never overwrites existing (collision suffix used)
      - Status always draft; never canonical
    """
    body = req.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Body is empty. Nothing saved.")

    title = req.title.strip() or "Untitled note"

    try:
        result = input_surface.save_markdown_note(
            title=title,
            body=body,
            topics=[t.strip() for t in req.topics if t.strip()],
            target_folder=req.target_folder or "notes",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save failed: {e}")

    return {
        "ok":          True,
        "doc_id":      result["doc_id"],
        "path":        result["path"],
        "indexed":     result["indexed"],
        "lint_errors": result["lint_errors"],
    }


@router.post("/upload", summary="Upload one or more files into the managed library")
async def upload_files(
    files:         list[UploadFile],
    target_folder: str = "scratch",
    intake_mode:   str = "scratch",
    project:       str = "",
    document_class: str = "",
    status:        str = "",
    canonical_layer: str = "",
    title:         str = "",
    provenance:    str = "upload",
    document_id:   str = "",
    source_hash:   str = "",
):
    """Upload files into the managed library.

    Accepted extensions: .md .txt .markdown .rst .csv .json .html .htm .yaml .yml
    Rejected: empty files, unsafe filenames, unsupported extensions.
    Collision: adds -2, -3 suffix instead of overwriting.
    .md/.txt files without BOH frontmatter get minimal frontmatter injected.
    """
    if not files:
        raise HTTPException(status_code=422, detail="No files provided.")

    saved    = []
    rejected = []

    for upload in files:
        try:
            content_bytes = await upload.read()
            metadata = {
                "project": project,
                "document_class": document_class,
                "status": status,
                "canonical_layer": canonical_layer,
                "title": title or (upload.filename or "upload"),
                "provenance": provenance,
                "source_hash": source_hash,
                "document_id": document_id,
            }
            result = input_surface.save_upload(
                filename=upload.filename or "upload",
                content_bytes=content_bytes,
                target_folder=target_folder or "scratch",
                intake_mode=intake_mode,
                metadata=metadata,
            )
            if "reason" in result:
                rejected.append({"filename": upload.filename, "reason": result["reason"]})
            else:
                saved.append({
                    "filename":    result["filename"],
                    "path":        result["path"],
                    "indexed":     result["indexed"],
                    "doc_id":      result.get("doc_id"),
                    "lint_errors": result.get("lint_errors", []),
                })
        except ValueError as e:
            rejected.append({"filename": getattr(upload, "filename", "?"), "reason": str(e)})
        except Exception as e:
            rejected.append({"filename": getattr(upload, "filename", "?"),
                             "reason": f"error: {e}"})

    return {"ok": True, "saved": saved, "rejected": rejected}


@router.get("/recent", summary="Recent browser-created or imported documents")
def recent_intake(limit: int = 20):
    """Return recent browser intake events from the audit log.

    Falls back to last 20 save events from audit_log table.
    """
    try:
        from app.core.audit import get_events
        events = get_events(event_type="save", limit=limit)
        return {
            "items": [
                {
                    "event_ts":  e.get("event_ts"),
                    "doc_id":    e.get("doc_id"),
                    "actor_id":  e.get("actor_id"),
                    "detail":    e.get("detail"),
                }
                for e in events
                if e.get("actor_id") in ("browser", "human")
            ]
        }
    except Exception as e:
        return {"items": [], "error": str(e)}


@router.post("/demo-seed", summary="Load Phase 16.1 demo projects with success and refusal cases")
def load_demo_seed():
    """Create fake, local test data for visualization and governance review."""
    demo_notes = [
        ("Hospital LOS", "ER throughput notes", "# ER Throughput Notes\n\nFake test data. ΩV declines as boarding pressure rises. Π increases when admission bottlenecks exceed staffing slack. H accumulates across shift handoff. Δc* should drift before KPI failure.", ["demo", "ΩV", "Π", "H", "Δc*", "hospital-los"]),
        ("Hospital LOS", "Boarding delay analysis", "# Boarding Delay Analysis\n\nFake test data. Admission bottleneck reviews show Load Conservation: unresolved ED work transfers to inpatient bed management.", ["demo", "Load Conservation", "boarding", "hospital-los"]),
        ("Hospital LOS", "Staffing mismatch report", "# Staffing Mismatch Report\n\nFake test data. Constraint Boundary crossed when arrival rate exceeds staffed review bandwidth.", ["demo", "Constraint Boundary", "Π", "H"]),
        ("E. coli Viability", "Growth phase observations", "# Growth Phase Observations\n\nFake test data. ΩV remains high through early growth. Nutrient constraint begins narrowing the viability region A_s.", ["demo", "ΩV", "A_s", "e-coli"]),
        ("E. coli Viability", "Stress response drift", "# Stress Response Drift\n\nFake test data. H accumulates under thermal and nutrient stress. Constraint Geometry marks a threshold event rather than semantic similarity.", ["demo", "H", "Constraint Geometry", "viability"]),
        ("Corporate Governance", "Authority transfer failure", "# Authority Transfer Failure\n\nFake test data. Approval remains documented, but refusal becomes structurally expensive. This maps to Asymmetric Absorption and Π.", ["demo", "Asymmetric Absorption", "Π", "governance"]),
        ("Corporate Governance", "Metric substitution example", "# Metric Substitution Example\n\nFake test data. Plane Collapse appears when financial throughput replaces operational truth. L_P rises as executive projection loses local context.", ["demo", "Plane Collapse", "L_P", "Projection Loss"]),
        ("Corporate Governance", "Load shedding analysis", "# Load Shedding Analysis\n\nFake test data. Risk is transferred downward rather than removed. This is a refusal candidate for bad canonical promotion.", ["demo", "Load Conservation", "Asymmetric Absorption"]),
        ("Governance Failure Cases", "Rejected review artifact", "# Rejected Review Artifact\n\nFake test data. This artifact should be refused: it attempts to promote an unmapped semantic association to canonical status without provenance.", ["demo", "rejected", "review_artifact"]),
        ("Governance Failure Cases", "Bad duplicate candidate", "# Bad Duplicate Candidate\n\nFake test data. Similar title, different claim. The correct behavior is compare or ignore, not automatic dedupe.", ["demo", "bad duplicate", "refusal"]),
        ("Governance Failure Cases", "False cross-project suggestion", "# False Cross-Project Suggestion\n\nFake test data. Hospital LOS and E. coli both mention viability, but the edge should remain suggested until a user approves the variable mapping.", ["demo", "false suggestion", "ΩV"]),
        ("Governance Failure Cases", "Rollback event", "# Rollback Event\n\nFake test data. Superseded canonical must remain fossilized and recoverable; rollback anchors must remain visible in Advanced mode.", ["demo", "rollback", "superseded canonical"]),
        ("Governance Failure Cases", "Conflict escalation", "# Conflict Escalation\n\nFake test data. Contradictory claims require explicit governance review. Trust is demonstrated by refusal, not acceptance.", ["demo", "conflict", "refusal"]),
    ]
    created = []
    for project, title, body, topics in demo_notes:
        folder = "demo-phase-16-1/" + project.lower().replace(" ", "-").replace(".", "")
        result = input_surface.save_markdown_note(title=f"Demo: {title}", body=body, topics=topics, target_folder=folder)
        created.append({**result, "project": project})
        try:
            from app.db import connection as db
            db.execute("UPDATE docs SET project=?, document_class=?, canonical_layer=?, review_state=? WHERE doc_id=?", (project, "evidence" if "Failure" not in project else "review_artifact", "supporting", "needs_review", result.get("doc_id")))
        except Exception:
            pass
    return {"ok": True, "project": "Phase 16.1 Demo Systems", "created": len(created), "items": created, "includes_failure_cases": True}


@router.post("/demo-seed/daenary", summary="Load Phase 18 Daenary epistemic demo seed data")
def load_daenary_demo_seed():
    """Create 25 documents spanning the full Daenary epistemic state space.

    Covers: canonical, contained, canceled, expired, escalated, approved,
    ambiguous, likely-incorrect, cross-project contradiction, source mismatch.
    Each document has real epistemic_d/m/q/c/correction_status values that
    make the visualization modes produce visibly different layouts.
    """
    from app.db import connection as db
    import json, time, uuid

    # (title, project, layer, status, d, m, q, c, correction_status, valid_until, topics, body)
    SEEDS = [
        # 1. High-quality canonical anchor
        ("Canonical Viability Reference", "Daenary Demo", "canonical", "canonical",
         1, None, 0.94, 0.91, "accurate", None,
         "viability daenary canonical reference",
         "# Canonical Viability Reference\n\nHigh-quality, high-confidence canonical record. d=+1, q=0.94, c=0.91. This node should appear in the canonical viability zone."),

        # 2. High-quality, low-confidence — contain
        ("Ambiguous Evidence Node", "Daenary Demo", "supporting", "draft",
         0, "contain", 0.88, 0.32, "incomplete", "2027-01-01",
         "evidence ambiguous contain daenary",
         "# Ambiguous Evidence Node\n\nStrong evidence quality but interpretation is uncertain. d=0, m=contain, q=0.88, c=0.32. Should appear in contain zone (upper-left viability surface)."),

        # 3. Conflicting evidence — cancel
        ("Contradicted Claim", "Daenary Demo", "conflict", "conflict",
         0, "cancel", 0.70, 0.55, "conflicting", "2026-12-01",
         "contradiction cancel conflict daenary",
         "# Contradicted Claim\n\nTwo sources directly contradict this record. d=0, m=cancel, correction_status=conflicting. Cannot be canonicalized."),

        # 4. Outdated material — expired
        ("Expired Reference Record", "Daenary Demo", "supporting", "draft",
         1, None, 0.75, 0.80, "outdated", "2025-06-01",
         "expired outdated daenary reference",
         "# Expired Reference Record\n\nValid evidence, but valid_until=2025-06-01 has passed. d=+1, q=0.75, c=0.80. Should appear in expired lane."),

        # 5. High-cost escalation candidate
        ("High-Stakes Decision Node", "Daenary Demo", "review", "review_required",
         0, "contain", 0.82, 0.74, "incomplete", "2027-03-01",
         "escalation high-cost decision daenary",
         "# High-Stakes Decision Node\n\nHigh harm_if_wrong, high reversal_cost. d=0, m=contain, q=0.82, c=0.74. Meaning cost should trigger escalation review."),

        # 6. Low-cost approved
        ("Low-Cost Approved Note", "Daenary Demo", "supporting", "approved_patch",
         1, None, 0.80, 0.76, "accurate", "2027-06-01",
         "approved low-cost accurate daenary",
         "# Low-Cost Approved Note\n\nd=+1, q=0.80, c=0.76, correction_status=accurate. Low meaning cost. Should appear in approved lane."),

        # 7. Ambiguous supporting — contain with valid_until
        ("Contextually Ambiguous Note", "Daenary Demo", "supporting", "draft",
         0, "contain", 0.62, 0.58, "incomplete", "2027-02-01",
         "ambiguous context contain daenary",
         "# Contextually Ambiguous Note\n\nAmbiguous but not contradicted. d=0, m=contain, q=0.62, c=0.58. Borderline contain zone."),

        # 8. Likely incorrect — negative d
        ("Likely Incorrect Import", "Daenary Demo", "quarantine", "quarantine",
         -1, None, 0.28, 0.82, "likely_incorrect", "2026-11-01",
         "incorrect import likely_incorrect daenary",
         "# Likely Incorrect Import\n\nd=-1, q=0.28, c=0.82, correction_status=likely_incorrect. High confidence in a wrong claim. Lower-right viability quadrant."),

        # 9. Cross-project contradiction A
        ("Project A Claim", "Project Alpha", "supporting", "draft",
         1, None, 0.78, 0.70, "accurate", "2027-04-01",
         "cross-project alpha claim daenary",
         "# Project A Claim\n\nd=+1, q=0.78, c=0.70. This claim contradicts an equivalent record in Project Beta."),

        # 10. Cross-project contradiction B
        ("Project Beta Counter-Claim", "Project Beta", "conflict", "conflict",
         -1, None, 0.75, 0.68, "conflicting", "2026-12-01",
         "cross-project beta contradiction daenary",
         "# Project Beta Counter-Claim\n\nd=-1, correction_status=conflicting. Direct contradiction to Project Alpha claim."),

        # 11. Source reliability mismatch
        ("Unreliable Source Intake", "Daenary Demo", "quarantine", "draft",
         0, "contain", 0.35, 0.45, "likely_incorrect", "2027-01-15",
         "source reliability mismatch daenary",
         "# Unreliable Source Intake\n\nSource quality below threshold. d=0, m=contain, q=0.35, c=0.45. Viability surface: low zone."),

        # 12. High-quality / high-confidence supporting
        ("Strong Supporting Record", "Daenary Demo", "supporting", "draft",
         1, None, 0.87, 0.83, "accurate", "2027-06-01",
         "supporting accurate strong daenary",
         "# Strong Supporting Record\n\nd=+1, q=0.87, c=0.83. Just below canonical threshold. Upper-right viability zone."),

        # 13. Under review — correction pending
        ("Pending Correction Note", "Daenary Demo", "review", "review_required",
         0, "contain", 0.71, 0.64, "outdated", "2027-01-01",
         "review pending outdated daenary",
         "# Pending Correction Note\n\nd=0, m=contain, correction_status=outdated. Under active review. q=0.71, c=0.64."),

        # 14. Negated evidence
        ("Negated Evidence Record", "Daenary Demo", "conflict", "conflict",
         -1, None, 0.60, 0.73, "conflicting", "2026-10-01",
         "negated evidence daenary conflict",
         "# Negated Evidence Record\n\nd=-1, q=0.60, c=0.73. Evidence quality is adequate but direction is negated."),

        # 15. Raw import — no epistemic state
        ("Raw Imported Document", "Daenary Demo", "quarantine", "draft",
         None, None, None, None, None, None,
         "raw import unprocessed daenary",
         "# Raw Imported Document\n\nNo epistemic state assigned yet. Will appear in raw_imported lane. Waiting for Daenary pipeline processing."),

        # 16. Low-q, low-c — noise
        ("Low-Quality Noise Record", "Daenary Demo", "quarantine", "scratch",
         0, "contain", 0.18, 0.22, "incomplete", "2026-09-01",
         "noise low-quality scratch daenary",
         "# Low-Quality Noise Record\n\nd=0, m=contain, q=0.18, c=0.22. Low-zone viability surface. High meaning cost relative to signal."),

        # 17. Archived superseded
        ("Archived Superseded Version", "Daenary Demo", "archive", "superseded",
         1, None, 0.82, 0.85, "outdated", "2025-01-01",
         "archived superseded daenary historical",
         "# Archived Superseded Version\n\nPreviously canonical, now superseded. d=+1 but outdated. Should appear in archived lane."),

        # 18. Escalated high-cost
        ("Escalated Review Case", "Daenary Demo", "review", "review_required",
         0, "contain", 0.84, 0.79, "incomplete", "2027-05-01",
         "escalated high-cost review daenary",
         "# Escalated Review Case\n\nHigh harm_if_wrong (0.80), high reversal_cost (0.75). d=0, m=contain. Requires human review before canonical promotion."),

        # 19. Canceled due to contradiction
        ("Canceled Contradiction", "Project Alpha", "conflict", "conflict",
         0, "cancel", 0.65, 0.60, "conflicting", "2026-11-01",
         "canceled contradiction alpha daenary",
         "# Canceled Contradiction\n\nd=0, m=cancel, correction_status=conflicting. Direct contradiction detected. Canonicalization blocked."),

        # 20. High q / moderate c — contain boundary
        ("Contain Boundary Node", "Daenary Demo", "supporting", "draft",
         0, "contain", 0.86, 0.58, "incomplete", "2027-04-01",
         "contain boundary daenary evidence",
         "# Contain Boundary Node\n\nd=0, m=contain, q=0.86, c=0.58. Strong evidence, interpretation not yet resolved. Upper-left viability zone."),

        # 21. Overconfident weak evidence
        ("Overconfident Weak Node", "Daenary Demo", "quarantine", "draft",
         1, None, 0.22, 0.91, "likely_incorrect", "2027-01-01",
         "overconfident weak evidence daenary",
         "# Overconfident Weak Node\n\nd=+1, q=0.22, c=0.91. High confidence in weak evidence. Lower-right viability quadrant — dangerous pattern."),

        # 22. Moderate both axes — under review
        ("Moderate State Node", "Project Beta", "supporting", "draft",
         1, None, 0.68, 0.65, "incomplete", "2027-02-01",
         "moderate review beta daenary",
         "# Moderate State Node\n\nd=+1, q=0.68, c=0.65. Both axes moderate. Borderline viable quadrant, under review."),

        # 23. Canonical from Project Beta
        ("Beta Canonical Record", "Project Beta", "canonical", "canonical",
         1, None, 0.91, 0.88, "accurate", None,
         "canonical beta accurate daenary",
         "# Beta Canonical Record\n\nd=+1, q=0.91, c=0.88, correction_status=accurate. Strong canonical anchor for Project Beta."),

        # 24. Expired high-quality
        ("Expired High-Quality Record", "Project Alpha", "supporting", "draft",
         1, None, 0.89, 0.86, "outdated", "2025-03-01",
         "expired high-quality alpha daenary",
         "# Expired High-Quality Record\n\nd=+1, q=0.89, c=0.86 but valid_until=2025-03-01 has expired. Good evidence, stale. Expired lane."),

        # 25. Weak, contested, low validity
        ("Contested Low-Validity Node", "Daenary Demo", "conflict", "conflict",
         -1, None, 0.31, 0.44, "conflicting", "2025-12-01",
         "contested low-validity conflict daenary",
         "# Contested Low-Validity Node\n\nd=-1, q=0.31, c=0.44, expired, conflicting. All risk factors present. Low-zone viability surface, expired lane."),
    ]

    created = []
    errors = []

    for (title, project, layer, status, d, m, q, c, correction, valid_until, topics, body) in SEEDS:
        try:
            folder = "demo-phase18-daenary/" + project.lower().replace(" ", "-").replace(".", "")
            result = input_surface.save_markdown_note(
                title=f"[D18] {title}", body=body,
                topics=topics.split(), target_folder=folder,
            )
            doc_id = result.get("doc_id")
            if doc_id:
                db.execute(
                    """UPDATE docs SET
                        project=?, document_class=?, canonical_layer=?,
                        status=?, authority_state=?, review_state=?,
                        epistemic_d=?, epistemic_m=?, epistemic_q=?,
                        epistemic_c=?, epistemic_correction_status=?,
                        epistemic_valid_until=?, epistemic_last_evaluated=?,
                        custodian_review_state=?
                       WHERE doc_id=?""",
                    (
                        project, "evidence", layer,
                        status, "approved" if status == "canonical" else "non_authoritative",
                        "approved" if status == "canonical" else "pending",
                        d, m, q,
                        c, correction,
                        valid_until, "2026-04-28T12:00:00Z",
                        "canonical" if status == "canonical" else (
                            "canceled" if m == "cancel" else (
                            "contained" if m == "contain" else "raw")),
                        doc_id,
                    ),
                )
                created.append({**result, "project": project, "epistemic_d": d,
                                 "epistemic_q": q, "epistemic_c": c})
        except Exception as e:
            errors.append({"title": title, "error": str(e)})

    return {
        "ok": True,
        "project": "Phase 18 Daenary Epistemic Demo",
        "created": len(created),
        "errors": errors,
        "items": created,
        "note": "Load the Visualization panel to see epistemic state topology across all 4 modes.",
    }

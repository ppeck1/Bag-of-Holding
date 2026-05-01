"""app/api/routes/certificate_routes.py: Certificate Gate API for BOH v2.

Phase 20: All canonical mutations require a valid certificate.

Routes:
  POST /api/certificate/request            — Request a transition certificate
  POST /api/certificate/review             — Approve or reject a certificate
  GET  /api/certificate/pending            — List pending certificates
  GET  /api/certificate/{cert_id}          — Get a single certificate
  GET  /api/node/{node_id}/certificate-history — Full certificate history for a node
  GET  /api/lattice/events                 — Lattice event log (immutable)
  GET  /api/lattice/events/{node_id}       — Events for a specific node
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.certificate import (
    request_certificate, approve_certificate, reject_certificate,
    revoke_certificate, get_certificate, get_certificate_history,
    get_pending_certificates, get_approved_certificate_for_node,
    request_reversion_certificate, apply_canonical_promotion,
)
from app.core.constraint_lattice import (
    check_transition_legal, get_lattice_events, log_lattice_event,
)

router = APIRouter(tags=["certificates"])

# ── Pydantic models ────────────────────────────────────────────────────────────

class CertificateRequest(BaseModel):
    node_id:        str
    from_d:         Optional[int]   = None
    to_d:           int
    from_mode:      Optional[str]   = None
    to_mode:        Optional[str]   = None
    reason:         str
    evidence_refs:  list[str]
    issuer_type:    str             = "human"
    q:              float
    c:              float
    valid_until:    str
    cost_of_wrong:  Optional[str]   = None
    context_ref:    Optional[str]   = None
    authority_plane: str            = "verification"


class ReviewRequest(BaseModel):
    certificate_id: str
    action:         str        # "approve" | "reject" | "revoke"
    reviewed_by:    str
    review_note:    str        = ""


class ApplyPromotionRequest(BaseModel):
    node_id:        str
    certificate_id: str


class ReversionRequest(BaseModel):
    node_id:        str
    from_d:         int
    reason:         str
    evidence_refs:  list[str]
    q:              float
    c:              float
    valid_until:    str
    reviewed_by:    str
    context_ref:    Optional[str] = None
    authority_plane: str = "governance"


# ── Certificate endpoints ──────────────────────────────────────────────────────

@router.post("/api/certificate/request",
             summary="Request a d-state transition certificate")
def request_cert(req: CertificateRequest):
    """Request a certificate to authorize a d-state transition.

    Phase 20 rule: d=0 → ±1 requires explicit human-issued certificate.
    No automated, LLM, or projection-issued certificates are accepted.
    """
    result = request_certificate(
        node_id        = req.node_id,
        from_d         = req.from_d,
        to_d           = req.to_d,
        from_mode      = req.from_mode,
        to_mode        = req.to_mode,
        reason         = req.reason,
        evidence_refs  = req.evidence_refs,
        issuer_type    = req.issuer_type,
        q              = req.q,
        c              = req.c,
        valid_until    = req.valid_until,
        cost_of_wrong  = req.cost_of_wrong,
        context_ref    = req.context_ref,
        authority_plane= req.authority_plane,
    )
    if not result["ok"]:
        return {"ok": False, "errors": result["errors"]}
    return result


@router.post("/api/certificate/review",
             summary="Approve, reject, or revoke a certificate")
def review_cert(req: ReviewRequest):
    """Review a pending certificate.

    Action must be: 'approve', 'reject', or 'revoke'.
    Approval does NOT automatically apply the transition.
    A separate promotion request must be made via the custodian layer.
    """
    if req.action == "approve":
        return approve_certificate(req.certificate_id, req.reviewed_by, req.review_note)
    elif req.action == "reject":
        return reject_certificate(req.certificate_id, req.reviewed_by, req.review_note)
    elif req.action == "revoke":
        return revoke_certificate(req.certificate_id, req.reviewed_by, req.review_note)
    else:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action {req.action!r}. Must be: approve | reject | revoke",
        )




@router.post("/api/certificate/apply-canonical-promotion",
             summary="Apply approved certificate to canonical promotion")
def apply_certified_promotion(req: ApplyPromotionRequest):
    """Single legal canonical promotion door.

    Requires an approved, non-expired certificate. Writes permanent certificate
    lineage to the canonical document. No direct promote/admin/dev/demo bypass.
    """
    result = apply_canonical_promotion(req.node_id, req.certificate_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or result.get("errors"))
    return result

@router.get("/api/certificate/pending",
            summary="List all pending certificates")
def list_pending(limit: int = Query(100, ge=1, le=500)):
    certs = get_pending_certificates(limit=limit)
    return {"pending": certs, "count": len(certs)}


@router.get("/api/certificate/{certificate_id}",
            summary="Get a single certificate by ID")
def get_cert(certificate_id: str):
    cert = get_certificate(certificate_id)
    if not cert:
        raise HTTPException(status_code=404, detail=f"Certificate {certificate_id!r} not found")
    return {"certificate": cert}


@router.get("/api/node/{node_id}/certificate-history",
            summary="Full certificate history for a node (immutable)")
def cert_history(node_id: str):
    """Returns all certificates for a node, newest first.
    History is immutable — no certificates are ever deleted.
    """
    history = get_certificate_history(node_id)
    return {
        "node_id":  node_id,
        "history":  history,
        "count":    len(history),
        "immutable": True,
    }


@router.post("/api/certificate/reversion",
             summary="Request a canonical reversion certificate")
def request_reversion(req: ReversionRequest):
    """Request a reversion certificate (canonical → review → revert).
    Reversion is lawful and auditable. No silent rollback.
    Reversion also requires a certificate — history remains visible.
    """
    result = request_reversion_certificate(
        node_id       = req.node_id,
        from_d        = req.from_d,
        reason        = req.reason,
        evidence_refs = req.evidence_refs,
        q             = req.q,
        c             = req.c,
        valid_until   = req.valid_until,
        reviewed_by   = req.reviewed_by,
        context_ref   = req.context_ref,
    )
    if not result["ok"]:
        return {"ok": False, "errors": result["errors"]}
    return result


# ── Lattice event log endpoints ────────────────────────────────────────────────

@router.get("/api/lattice/events",
            summary="Global lattice event log (immutable)")
def get_events(limit: int = Query(100, ge=1, le=1000)):
    """Immutable lattice event log. Records forced collapses, approvals, rejections.
    No events are ever deleted.
    """
    events = get_lattice_events(limit=limit)
    return {"events": events, "count": len(events), "immutable": True}


@router.get("/api/lattice/events/{node_id}",
            summary="Lattice events for a specific node")
def get_node_events(node_id: str, limit: int = Query(100, ge=1, le=500)):
    events = get_lattice_events(node_id=node_id, limit=limit)
    return {"node_id": node_id, "events": events, "count": len(events)}


# ── Transition legality check (read-only) ─────────────────────────────────────

@router.get("/api/lattice/check",
            summary="Check if a d-state transition is lattice-legal")
def check_transition(
    from_d:         Optional[int] = Query(None),
    to_d:           int           = Query(...),
    certificate_id: Optional[str] = Query(None),
):
    """Non-mutating legality check. Does not apply any transition.
    Use before requesting a certificate to understand risk class and thresholds.
    """
    cert = None
    if certificate_id:
        cert = get_certificate(certificate_id)
        if not cert:
            raise HTTPException(status_code=404, detail=f"Certificate {certificate_id!r} not found")

    result = check_transition_legal(from_d=from_d, to_d=to_d, certificate=cert)
    return result

# Phase 20.1 dead legacy routes. They intentionally never mutate.
@router.post("/api/promote", summary="REMOVED: direct promotion")
@router.post("/api/node/promote", summary="REMOVED: direct promotion")
@router.post("/api/canonicalize", summary="REMOVED: direct canonicalization")
def direct_promotion_removed():
    raise HTTPException(status_code=410, detail="direct_promotion_removed_use_certificate_flow")

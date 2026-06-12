"""app/api/routes/plane_routes.py: PCDS Plane Card endpoints for BOH v2.

Phase 19: Plane Card storage conversion.

Routes:
  GET  /api/planes                  — list planes with card counts
  GET  /api/planes/cards            — list cards with filters
  GET  /api/planes/cards/{card_id}  — get a single card
  POST /api/planes/cards            — create a standalone card
  POST /api/planes/backfill         — wrap all docs as cards (migration)
  GET  /api/docs/{doc_id}/card      — get the PlaneCard wrapping a document
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.plane_card import (
    PlaneCard, wrap_document_as_card, upsert_card, get_card,
    get_card_for_doc, list_cards, list_planes, backfill_all_docs,
    create_llm_output_card, log_storage_event, validate_card, wrap_and_persist,
)
from app.core.auth import require_operator
from app.db import connection as db

router = APIRouter(prefix="/api/planes", tags=["planes"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class CreateCardRequest(BaseModel):
    plane:       str
    card_type:   str = "observation"
    topic:       str
    b:           int = 0
    d:           Optional[int]   = None
    m:           Optional[str]   = None
    delta:       Optional[dict]  = None
    constraints: Optional[dict]  = None
    authority:   Optional[dict]  = None
    observed_at: Optional[str]   = None
    valid_until: Optional[str]   = None
    context_ref: Optional[dict]  = None
    payload:     Optional[dict]  = None
    doc_id:      Optional[str]   = None


class LLMOutputCardRequest(BaseModel):
    topic: str
    text: str
    source_ref: Optional[dict] = None
    actor_id: str = "llm"
    model: Optional[str] = None


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("", summary="List all planes with card counts")
def get_planes():
    """Returns a list of all distinct planes in the cards table."""
    planes = list_planes()
    return {"planes": planes, "count": len(planes)}


@router.get("/registry", summary="List registered Planar Storage planes")
def get_plane_registry():
    rows = db.fetchall("SELECT * FROM planes ORDER BY plane_id")
    return {"planes": rows, "count": len(rows)}


@router.get("/cards", summary="List PlaneCards with optional filters")
def get_cards(
    plane:      Optional[str]   = Query(None, description="Filter by plane name"),
    card_type:  Optional[str]   = Query(None, description="Filter by card type"),
    d:          Optional[int]   = Query(None, description="Filter by d-state (-1, 0, 1)"),
    m:          Optional[str]   = Query(None, description="Filter by zero-mode (contain/cancel)"),
    q_min:      Optional[float] = Query(None, description="Minimum epistemic_q"),
    c_min:      Optional[float] = Query(None, description="Minimum epistemic_c"),
    valid_now:  bool            = Query(False, description="Only non-expired cards"),
    expired:    bool            = Query(False, description="Only expired cards"),
    limit:      int             = Query(100, ge=1, le=500),
    offset:     int             = Query(0, ge=0),
):
    """List PlaneCards with multi-dimensional filtering.

    This is the Phase 19 retrieval foundation — Phase 22 will add full
    plane-aware search against topic + validity + certificate.
    """
    cards = list_cards(
        plane=plane, card_type=card_type, d=d, m=m,
        q_min=q_min, c_min=c_min,
        valid_now=valid_now, expired=expired,
        limit=limit, offset=offset,
    )
    return {
        "cards": [c.to_dict() for c in cards],
        "count": len(cards),
        "filters": {
            "plane": plane, "card_type": card_type,
            "d": d, "m": m, "q_min": q_min, "c_min": c_min,
            "valid_now": valid_now, "expired": expired,
        },
    }


@router.get("/cards/{card_id}", summary="Get a single PlaneCard by ID")
def get_card_by_id(card_id: str):
    """Retrieve a PlaneCard by its CARD:... identifier."""
    card = get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"Card {card_id!r} not found")
    return {"card": card.to_dict()}


@router.post("/cards", summary="Create a standalone PlaneCard")
def create_card(req: CreateCardRequest, _operator: str = Depends(require_operator)):
    """Create a new PlaneCard directly (not wrapping a document).

    Useful for storing observations, claims, or evidence records that do
    not originate from an indexed markdown document.
    """
    import time
    from app.core.plane_card import _card_id as _cid
    import uuid as _uuid

    synthetic_id = str(_uuid.uuid4())[:8]
    card = PlaneCard(
        id          = f"CARD:manual:{synthetic_id}",
        plane       = req.plane,
        card_type   = req.card_type,
        topic       = req.topic,
        b           = req.b,
        d           = req.d,
        m           = req.m,
        delta       = req.delta       or {"kind": "scalar", "dims": [], "value": []},
        constraints = req.constraints or {"context": f"C:{req.plane}:Standard", "requires_certificate_for_base_flip": True},
        authority   = req.authority   or {"write": ["user"], "resolve": ["user"]},
        observed_at = req.observed_at,
        valid_until = req.valid_until,
        context_ref = req.context_ref or {},
        payload     = req.payload     or {},
        doc_id      = req.doc_id,
        created_ts  = int(time.time()),
        updated_ts  = int(time.time()),
    )
    errors = validate_card(card)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    upsert_card(card)
    log_storage_event(
        "candidate_created",
        subject_type="plane_card",
        subject_id=card.id,
        plane=card.plane,
        card_id=card.id,
        doc_id=card.doc_id,
        detail={"card_type": card.card_type, "manual": True},
    )
    return {"ok": True, "card": card.to_dict()}


@router.post("/llm-output", summary="Record LLM output as a subjective non-authoritative PlaneCard")
def create_llm_card(req: LLMOutputCardRequest, _operator: str = Depends(require_operator)):
    card = create_llm_output_card(
        topic=req.topic,
        text=req.text,
        source_ref=req.source_ref,
        actor_id=req.actor_id,
        model=req.model,
    )
    return {"ok": True, "card": card.to_dict()}


@router.post("/wrap/{doc_id}", summary="Wrap an existing source document as a PlaneCard")
def wrap_doc(doc_id: str, _operator: str = Depends(require_operator)):
    doc = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id!r} not found")
    card = wrap_and_persist(dict(doc))
    return {"ok": True, "card": card.to_dict(), "source_preserved": True}


@router.post("/backfill", summary="Wrap all indexed documents as PlaneCards")
def backfill(_operator: str = Depends(require_operator)):
    """Migration endpoint: wrap every document in the docs table as a PlaneCard.

    Safe to call multiple times — uses INSERT OR REPLACE (upsert).
    """
    result = backfill_all_docs()
    return {"ok": True, **result}


@router.get("/storage-events", summary="List Planar Storage trace events")
def get_storage_events(
    event_type: Optional[str] = Query(None),
    card_id: Optional[str] = Query(None),
    doc_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    wheres = []
    params: list = []
    if event_type:
        wheres.append("event_type = ?")
        params.append(event_type)
    if card_id:
        wheres.append("card_id = ?")
        params.append(card_id)
    if doc_id:
        wheres.append("doc_id = ?")
        params.append(doc_id)
    sql = "SELECT * FROM storage_events"
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY created_ts DESC LIMIT ?"
    params.append(limit)
    events = db.fetchall(sql, tuple(params))
    return {"events": events, "count": len(events)}


# ── Doc-scoped card endpoint (registered on docs prefix) ──────────────────────
# Note: this uses a separate router so it can be at /api/docs/{doc_id}/card

doc_card_router = APIRouter(prefix="/api/docs", tags=["planes"])


@doc_card_router.get("/{doc_id}/card", summary="Get the PlaneCard wrapping a document")
def get_doc_card(doc_id: str):
    """Returns the PCDS PlaneCard for an existing document.

    If no card exists yet, auto-wraps and persists before returning.
    """
    card = get_card_for_doc(doc_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"Document {doc_id!r} not found")
    return {"card": card.to_dict()}

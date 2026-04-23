"""app/api/routes/events.py"""
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from app.services import events as event_engine

router = APIRouter(prefix="/api")

@router.get("/events/export.ics", response_class=PlainTextResponse, summary="Export events as ICS")
def export_ics(doc_id: Optional[str] = Query(None)):
    return event_engine.export_ics(doc_id=doc_id)

@router.get("/events", summary="List all events")
def list_events(doc_id: Optional[str] = Query(None)):
    evs = event_engine.list_events(doc_id=doc_id)
    return {"count": len(evs), "events": evs}

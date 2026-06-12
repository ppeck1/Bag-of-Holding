"""app/api/routes/canon.py"""
from typing import Optional
from fastapi import APIRouter, Query
from app.core import canon as canon_engine

router = APIRouter(prefix="/api")

@router.get("/canon", summary="Resolve canonical document")
def resolve_canon(
    topic: Optional[str] = Query(None),
    plane: Optional[str] = Query(None),
):
    return canon_engine.resolve_canon(topic=topic, plane_scope=plane)

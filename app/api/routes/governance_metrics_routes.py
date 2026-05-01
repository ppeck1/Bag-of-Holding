"""Governance-native observability routes."""
from __future__ import annotations
from fastapi import APIRouter, Query
from app.core.governance_metrics import governance_native_metrics

router = APIRouter(prefix="/api/governance", tags=["governance-observability"])

@router.get("/metrics", summary="Phase 25.1 governance-native metrics")
def api_governance_metrics(limit: int = Query(50, ge=1, le=200)):
    return governance_native_metrics(limit=limit)

"""app/api/routes/trace_routes.py: Phase 7 Trace Ledger surface (read-only).

Exposes the existing gate-result ledger so every gate decision is inspectable and
a batch can be followed to its gate status. Backed solely by the read-only
accessors in `app.core.correction_ledger`; performs no writes and never grants
canon eligibility.

GET /api/trace/gate-results              — recent gate results (limit, posture filter)
GET /api/trace/gate-results/{id}         — a single gate result, or 404
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core import correction_ledger

router = APIRouter(prefix="/api/trace", tags=["trace"])

MAX_LIMIT = 200


def _sanitize(value: Any) -> Any:
    """Recursively force any `canon_eligible` to False; the trace surface never
    grants canon eligibility, even via an embedded snapshot blob."""
    if isinstance(value, dict):
        return {k: (False if k == "canon_eligible" else _sanitize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _strip_raw_json(row: dict[str, Any]) -> dict[str, Any]:
    """Drop the redundant raw `*_json` string columns; the ledger already returns
    decoded counterparts (e.g. `blocking_reasons` for `blocking_reasons_json`)."""
    return {k: v for k, v in row.items() if not k.endswith("_json")}


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return _sanitize(_strip_raw_json(row))


@router.get("/gate-results", summary="List recent gate results (read-only trace ledger)")
def list_gate_results(
    limit: int = Query(50, ge=1),
    posture: Optional[str] = Query(None),
):
    rows = correction_ledger.list_gate_results(limit=min(limit, MAX_LIMIT), posture=posture)
    return {"gate_results": [_clean(r) for r in rows]}


@router.get("/gate-results/{gate_result_id}", summary="Get one gate result, or 404")
def get_gate_result(gate_result_id: str):
    row = correction_ledger.get_gate_result(gate_result_id)
    if row is None:
        raise HTTPException(status_code=404, detail="gate result not found")
    return _clean(row)

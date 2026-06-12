"""app/api/routes/residence_routes.py: Phase 7 Residence Map surface (read-only).

Exposes the information-residence map so you can see where information now lives
after corrections (original -> current location/status). Backed solely by the
read-only accessors in `app.core.correction_ledger`; performs no writes and never
grants canon eligibility. Residence rows are written elsewhere (as a side effect of
approving a patch proposal); this surface only inspects them.

GET /api/residence/map                 — residence rows (limit, status filter)
GET /api/residence/map/{original_ref}  — latest row for a ref, or 404
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core import correction_ledger

router = APIRouter(prefix="/api/residence", tags=["residence"])

MAX_LIMIT = 200


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (False if k == "canon_eligible" else _sanitize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return _sanitize({k: v for k, v in row.items() if not k.endswith("_json")})


@router.get("/map", summary="List information-residence rows (read-only)")
def list_residences(
    limit: int = Query(50, ge=1),
    status: Optional[str] = Query(None),
):
    rows = correction_ledger.list_information_residence(limit=min(limit, MAX_LIMIT), status=status)
    return {"residences": [_clean(r) for r in rows]}


@router.get("/map/{original_ref}", summary="Get the latest residence row for a ref, or 404")
def get_residence(original_ref: str):
    row = correction_ledger.get_information_residence(original_ref)
    if row is None:
        raise HTTPException(status_code=404, detail="information_residence_not_found")
    return _clean(row)

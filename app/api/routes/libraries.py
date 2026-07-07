"""Logical library registry and presentation controls for the /v2 Library screen."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import audit_operator_action, require_operator
from app.core.logical_libraries import (
    InvalidLibraryId,
    list_logical_libraries,
    reset_logical_library_override,
    set_logical_library_order,
    update_logical_library_override,
)

router = APIRouter(prefix="/api", tags=["libraries"])


class LibraryOverrideRequest(BaseModel):
    display_name: Optional[str] = None
    hidden: Optional[bool] = None
    sort_order: Optional[int] = None


class LibraryOrderRequest(BaseModel):
    ids: list[str]


def _set_fields(model: BaseModel) -> set[str]:
    fields = getattr(model, "model_fields_set", None)
    if fields is None:
        fields = getattr(model, "__fields_set__", set())
    return set(fields)


def _http_for_library_error(exc: Exception, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/libraries", summary="List logical libraries derived from indexed paths")
def get_libraries(include_hidden: bool = Query(False, description="Include hidden libraries for management")):
    libraries = [library.to_dict() for library in list_logical_libraries(include_hidden=include_hidden)]
    return {"libraries": libraries, "count": len(libraries)}


@router.patch("/libraries/order", summary="Reorder logical library display list")
def reorder_libraries(req: LibraryOrderRequest, _operator: str = Depends(require_operator)):
    if not req.ids:
        raise HTTPException(status_code=422, detail="ids must not be empty")
    try:
        libraries = [library.to_dict() for library in set_logical_library_order(req.ids)]
    except InvalidLibraryId as exc:
        raise _http_for_library_error(exc, status_code=404)
    except ValueError as exc:
        raise _http_for_library_error(exc, status_code=422)
    audit_operator_action(
        "logical_library_override",
        "reorder",
        {"library_ids": req.ids},
    )
    return {"ok": True, "libraries": libraries, "count": len(libraries)}


@router.patch("/libraries/{library_id}", summary="Update logical library display metadata")
def update_library(
    library_id: str,
    req: LibraryOverrideRequest,
    _operator: str = Depends(require_operator),
):
    fields = _set_fields(req)
    if not fields:
        raise HTTPException(status_code=422, detail="At least one override field is required")
    try:
        library = update_logical_library_override(
            library_id,
            display_name=req.display_name if "display_name" in fields else None,
            hidden=req.hidden if "hidden" in fields else None,
            sort_order=req.sort_order if "sort_order" in fields else None,
            clear_display_name=("display_name" in fields and req.display_name is None),
            clear_sort_order=("sort_order" in fields and req.sort_order is None),
        )
    except InvalidLibraryId as exc:
        raise _http_for_library_error(exc, status_code=404)
    except ValueError as exc:
        raise _http_for_library_error(exc, status_code=422)
    audit_operator_action(
        "logical_library_override",
        "update",
        {"library_id": library_id, "fields": sorted(fields)},
    )
    return {"ok": True, "library": library.to_dict()}


@router.delete("/libraries/{library_id}/override", summary="Reset logical library display metadata")
def reset_library(library_id: str, _operator: str = Depends(require_operator)):
    try:
        library = reset_logical_library_override(library_id)
    except InvalidLibraryId as exc:
        raise _http_for_library_error(exc, status_code=404)
    audit_operator_action(
        "logical_library_override",
        "reset",
        {"library_id": library_id},
    )
    return {"ok": True, "library": library.to_dict()}

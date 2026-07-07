"""app/api/routes/context_pack_routes.py: Phase 7 Context Pack Builder surface.

Exposes the Phase 6 Context Assembly service so its labeled output is inspectable.
Read-only: it assembles a SUPPLIED candidate-pack list (no retrieval path) by
composing `context_assembly.assemble`, which is pure, deterministic, and never sets
canon_eligible. Performs no DB writes.

POST /api/context-pack/assemble        — assemble supplied candidate packs
GET  /api/context-pack/section-labels  — the fixed section labels
"""

from __future__ import annotations

from typing import Any, Optional, Union

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core import context_assembly

router = APIRouter(prefix="/api/context-pack", tags=["context-pack"])


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (False if k == "canon_eligible" else _sanitize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


class AssembleRequest(BaseModel):
    query: str
    operation: str = "answer_context"
    actor: Optional[Union[str, dict[str, Any]]] = None
    mode: str = "exploration"
    candidate_packs: list[dict[str, Any]] = Field(default_factory=list)
    governance_health: Optional[dict[str, Any]] = None


@router.post("/assemble", summary="Assemble a supplied candidate-pack list (read-only)")
def assemble_context_pack(req: AssembleRequest):
    result = context_assembly.assemble(
        query=req.query,
        operation=req.operation,
        actor=req.actor,
        mode=req.mode,
        candidate_packs=req.candidate_packs,
        governance_health=req.governance_health,
    )
    return _sanitize(result.to_dict())


@router.get("/section-labels", summary="The fixed context-pack section labels")
def section_labels():
    return {"section_labels": list(context_assembly.SECTION_LABELS)}

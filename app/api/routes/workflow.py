"""app/api/routes/workflow.py"""
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from app.core.auth import require_operator
from app.core import actor_ledger as al
from app.db import connection as db
from app.core.rubrix import (
    ALLOWED_TRANSITIONS, OPERATOR_STATES, OPERATOR_INTENTS,
    VALID_STATUSES, validate_header,
)

router = APIRouter(prefix="/api")


@router.get("/workflow", summary="List documents and their Rubrix workflow states")
def workflow(
    operator_state: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
):
    query = "SELECT doc_id, path, type, status, operator_state, operator_intent, version FROM docs WHERE 1=1"
    params = []
    if operator_state:
        query += " AND operator_state = ?"
        params.append(operator_state)
    if status:
        query += " AND status = ?"
        params.append(status)
    if doc_type:
        query += " AND type = ?"
        params.append(doc_type)
    query += " ORDER BY operator_state, status"
    docs = db.fetchall(query, tuple(params))
    return {
        "count": len(docs),
        "docs": docs,
        "rubrix_schema": {
            "operator_states": list(OPERATOR_STATES),
            "operator_intents": list(OPERATOR_INTENTS),
            "allowed_transitions": {k: list(v) for k, v in ALLOWED_TRANSITIONS.items()},
            "hard_constraints": [
                "status=canonical ⇒ operator_state=release",
                "type=canon ⇒ operator_state≠observe",
                "status=archived ⇒ operator_state=release",
            ],
        },
    }


class WorkflowTransitionRequest(BaseModel):
    operator_state: str
    operator_intent: str


@router.patch("/workflow/{doc_id}", summary="Transition a document's Rubrix operator_state")
def transition_workflow(
    doc_id: str,
    req: WorkflowTransitionRequest,
    _operator: str = Depends(require_operator),
    x_boh_actor_id: Optional[str] = Header(default=None, alias="X-BOH-Actor-ID"),
):
    """Advance a document through the Rubrix lifecycle.

    Enforces ALLOWED_TRANSITIONS and all hard constraints (R6, R7, R8).
    Does not modify the source file — updates DB record only.
    User must re-index or manually edit frontmatter to make persistent.
    """
    # WO-2 mutation isolation (gate-independent): promoted intake docs are not workflow-mutable.
    from app.core import promoted_exposure
    if promoted_exposure.is_promoted_doc_id(doc_id):
        raise HTTPException(status_code=409, detail=promoted_exposure.MUTATION_BLOCK_REASON)
    doc = db.fetchone(
        "SELECT doc_id, type, status, operator_state, operator_intent FROM docs WHERE doc_id = ?",
        (doc_id,),
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    current_state = doc["operator_state"]
    new_state = req.operator_state
    new_intent = req.operator_intent

    # Validate new state is in ontology
    if new_state not in OPERATOR_STATES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid operator_state '{new_state}'. Must be one of {sorted(OPERATOR_STATES)}",
        )
    if new_intent not in OPERATOR_INTENTS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid operator_intent '{new_intent}'. Must be one of {sorted(OPERATOR_INTENTS)}",
        )

    # Enforce ALLOWED_TRANSITIONS (R10)
    allowed = ALLOWED_TRANSITIONS.get(current_state, set())
    if new_state not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Transition from '{current_state}' to '{new_state}' is not allowed. "
                f"Allowed next states: {sorted(allowed)}"
            ),
        )

    # Hard constraints (R6, R7, R8) — check against current doc status/type
    errors = []
    doc_status = doc["status"]
    doc_type = doc["type"]

    if doc_status == "canonical" and new_state != "release":
        errors.append(f"LINT_CONSTRAINT_VIOLATION: status=canonical requires operator_state=release")
    if doc_type == "canon" and new_state == "observe":
        errors.append("LINT_CONSTRAINT_VIOLATION: type=canon cannot have operator_state=observe")
    if doc_status == "archived" and new_state != "release":
        errors.append(f"LINT_CONSTRAINT_VIOLATION: status=archived requires operator_state=release")

    if errors:
        raise HTTPException(status_code=422, detail={"constraint_violations": errors})

    db.execute(
        "UPDATE docs SET operator_state = ?, operator_intent = ? WHERE doc_id = ?",
        (new_state, new_intent, doc_id),
    )
    al.ledger_event("transition_lifecycle", "document", doc_id,
                    actor_id=al.actor_from_env_or_header(x_boh_actor_id),
                    authority_result="allowed", authority_basis="operator_token_fallback",
                    before={"operator_state": current_state, "operator_intent": doc["operator_intent"]},
                    after={"operator_state": new_state, "operator_intent": new_intent},
                    source_route=f"/api/workflow/{doc_id}")
    al.add_document_attribution(doc_id, "modified_by", al.actor_from_env_or_header(x_boh_actor_id),
                                source="workflow_transition",
                                evidence={"operator_state": new_state, "operator_intent": new_intent})

    return {
        "doc_id": doc_id,
        "previous_state": current_state,
        "new_state": new_state,
        "new_intent": new_intent,
        "success": True,
        "note": "DB record updated. Re-index from source file to make permanent.",
    }

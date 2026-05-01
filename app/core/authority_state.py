"""Phase 14 canonical authority lock helpers."""
from __future__ import annotations
from app.db import connection as db
from app.core.metadata_contract import can_transition


def assert_import_transition(doc_id: str, incoming_status: str, approved: bool = False) -> None:
    row = db.fetchone("SELECT status FROM docs WHERE doc_id = ?", (doc_id,))
    old = row.get("status") if row else "raw"
    ok, reason = can_transition(old, incoming_status, approved=approved)
    if not ok:
        raise ValueError(reason)


def authority_score(status: str, canonical_layer: str, review_state: str = "") -> float:
    if status == "canonical" and canonical_layer == "canonical" and review_state in {"approved", ""}:
        return 0.95
    if status in {"superseded", "archived"}: return 0.25
    if canonical_layer == "evidence": return 0.55
    if canonical_layer == "supporting": return 0.65
    if canonical_layer == "review": return 0.35
    if status in {"scratch", "legacy"} or canonical_layer == "quarantine": return 0.05
    return 0.45

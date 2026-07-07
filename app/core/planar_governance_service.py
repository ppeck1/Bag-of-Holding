"""PlanarGovernanceService -- a single deterministic governance entrypoint.

This is a thin composition layer over the existing, individually-tested Phase 5
components. It introduces NO new policy logic: it calls the established
evaluators and aggregates their results into one GovernanceDecision so that
downstream consumers (context assembly, UI) read from one stable surface.

Composed components:
  - app.core.planar_gate.evaluate_context_pack  -> posture, withheld context, gates
  - app.core.planar_authority.can_use/can_promote -> fail-closed authority binding
  - app.core.metadata_contract.can_transition    -> authority-transition state machine
  - injected conflicts (e.g. app.core.conflicts.list_conflicts)

Read-only by contract: this service performs no writes, never mutates the DB,
and never sets canon_eligible. It is deterministic -- the same inputs yield an
equal GovernanceDecision.to_dict() (no wall-clock field is included).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core import planar_authority, planar_gate
from app.core.metadata_contract import can_transition


_BLOCKED_POSTURE = "blocked"


def _stable_decision_id(
    operation: str,
    gate_result_id: str,
    transition: tuple[str, str, bool] | None,
    conflict_ids: list[str],
    authority_allowed: bool,
) -> str:
    raw = json.dumps(
        {
            "operation": operation,
            "gate_result_id": gate_result_id,
            "transition": list(transition) if transition else None,
            "conflict_ids": sorted(conflict_ids),
            "authority_allowed": authority_allowed,
        },
        sort_keys=True,
        default=str,
    )
    return "gov_" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


@dataclass
class GovernanceDecision:
    """Aggregated, deterministic governance verdict for one evaluation.

    Carries no wall-clock timestamp so it is reproducible. canon_eligible is
    re-forced to False -- this service never grants canon eligibility.
    """

    operation: str
    posture: str
    allowed: bool
    context_pack_id: str
    gate_result_id: str
    trace_event_type: str
    blocking_reasons: list[str] = field(default_factory=list)
    warning_reasons: list[str] = field(default_factory=list)
    allowed_context_refs: list[str] = field(default_factory=list)
    withheld_context_refs: list[str] = field(default_factory=list)
    authority: dict[str, Any] | None = None
    transition_ok: bool | None = None
    transition_reason: str | None = None
    conflict_count: int = 0
    conflict_ids: list[str] = field(default_factory=list)
    canon_eligible: bool = False  # INVARIANT: always False
    decision_id: str = ""

    def __post_init__(self) -> None:
        self.canon_eligible = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_transition(transition: Any) -> tuple[str, str, bool] | None:
    """Accept (old, new), (old, new, approved), or a dict; return a 3-tuple."""
    if transition is None:
        return None
    if isinstance(transition, dict):
        old = transition.get("old_status") or transition.get("old")
        new = transition.get("new_status") or transition.get("new")
        approved = bool(transition.get("approved", False))
        if old is None or new is None:
            return None
        return (str(old), str(new), approved)
    if isinstance(transition, (list, tuple)):
        if len(transition) == 2:
            return (str(transition[0]), str(transition[1]), False)
        if len(transition) >= 3:
            return (str(transition[0]), str(transition[1]), bool(transition[2]))
    return None


def _conflict_ids(conflicts: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for c in conflicts:
        cid = c.get("conflict_id") or c.get("id")
        if cid:
            ids.append(str(cid))
    return ids


def evaluate(
    actor: str | dict[str, Any] | None,
    *,
    query: str,
    operation: str,
    mode: str,
    candidate_packs: list[dict[str, Any]],
    card: Any | None = None,
    target_plane: str | None = None,
    certificate: dict[str, Any] | None = None,
    transition: Any = None,
    conflicts: list[dict[str, Any]] | None = None,
    governance_health: dict[str, Any] | None = None,
) -> GovernanceDecision:
    """Compose the Phase 5 evaluators into one GovernanceDecision.

    Pure composition: delegates posture/withheld-context to planar_gate,
    authority binding to planar_authority (only when a `card` is supplied),
    transition validity to metadata_contract.can_transition (only when a
    `transition` is supplied), and conflict status from the injected
    `conflicts` list (callers pass conflicts.list_conflicts()).

    Performs no writes and reads no DB itself; deterministic for fixed inputs.
    """
    operation_key = str(operation or "answer_context").lower()

    _context, gate = planar_gate.evaluate_context_pack(
        query=query,
        operation=operation_key,
        actor=actor,
        mode=mode,
        candidate_packs=candidate_packs,
        governance_health=governance_health,
    )

    posture = gate["posture"]
    gate_allowed = posture != _BLOCKED_POSTURE

    authority_dict: dict[str, Any] | None = None
    if card is not None:
        if operation_key == "promote":
            authority_dict = planar_authority.can_promote(
                actor, card, target_plane or "", certificate
            ).to_dict()
        else:
            authority_dict = planar_authority.can_use(
                actor, card, operation_key, mode
            ).to_dict()
    authority_allowed = True if authority_dict is None else bool(authority_dict.get("allowed", True))

    norm_transition = _normalize_transition(transition)
    transition_ok: bool | None = None
    transition_reason: str | None = None
    if norm_transition is not None:
        old_status, new_status, approved = norm_transition
        transition_ok, transition_reason = can_transition(old_status, new_status, approved=approved)

    conflict_list = conflicts or []
    conflict_ids = _conflict_ids(conflict_list)

    decision = GovernanceDecision(
        operation=operation_key,
        posture=posture,
        allowed=gate_allowed and authority_allowed,
        context_pack_id=gate["context_pack_id"],
        gate_result_id=gate["gate_result_id"],
        trace_event_type=gate["trace_event_type"],
        blocking_reasons=list(gate.get("blocking_reasons") or []),
        warning_reasons=list(gate.get("warning_reasons") or []),
        allowed_context_refs=list(gate.get("allowed_context_refs") or []),
        withheld_context_refs=list(gate.get("withheld_context_refs") or []),
        authority=authority_dict,
        transition_ok=transition_ok,
        transition_reason=transition_reason,
        conflict_count=len(conflict_list),
        conflict_ids=conflict_ids,
    )
    decision.decision_id = _stable_decision_id(
        operation_key, decision.gate_result_id, norm_transition, conflict_ids, authority_allowed
    )
    return decision

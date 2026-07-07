"""Fixture evaluator for Planar Storage gate behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core import planar_gate


def load_fixture_pack(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("id") == item_id), None)


def fixture_card_by_id(pack: dict[str, Any], card_id: str) -> dict[str, Any]:
    card = _by_id(pack.get("plane_cards") or [], card_id)
    if not card:
        raise KeyError(f"fixture card not found: {card_id}")
    return card


def actor_from_pack(pack: dict[str, Any], actor_id: str) -> dict[str, Any]:
    actor = _by_id(pack.get("actors") or [], actor_id)
    if actor:
        return {"actor_id": actor.get("id"), "role": actor.get("role"), "scope": actor.get("scope")}
    return {"actor_id": actor_id, "role": actor_id}


def _scalar_basis(pack: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    return _by_id(pack.get("scalar_basis_records") or [], ref)


def _authority_state(pack: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    return _by_id(pack.get("authority_states") or [], ref)


def _state_vector(pack: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    return _by_id(pack.get("semantic_state_vectors") or [], ref)


def _conflict_set(pack: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    return _by_id(pack.get("conflict_sets") or [], ref)


def _dominance_policy(pack: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    return _by_id(pack.get("dominance_policies") or [], ref)


def governance_health_from_pack(case: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    context = case.get("context_pack") or {}
    health_ref = context.get("governance_health") or (case.get("input_refs") or {}).get("governance_health")
    health = _by_id(pack.get("governance_health_snapshots") or [], health_ref) if health_ref else None
    conflict_ref = context.get("conflict_set")
    dominance_ref = context.get("dominance_policy")
    return {
        **(health or {}),
        "governance_health_ref": health_ref,
        "conflict_set_ref": conflict_ref,
        "dominance_policy_ref": dominance_ref,
    }


def candidate_packs_from_fixture_case(case: dict[str, Any], pack: dict[str, Any]) -> list[dict[str, Any]]:
    refs = ((case.get("input_refs") or {}).get("plane_cards") or
            (case.get("context_pack") or {}).get("candidate_cards") or [])
    candidates: list[dict[str, Any]] = []
    for ref in refs:
        card = fixture_card_by_id(pack, ref)
        scalar = _scalar_basis(pack, card.get("scalar_basis_ref"))
        authority = _authority_state(pack, card.get("authority_ref")) or {}
        state = _state_vector(pack, card.get("state_vector_ref")) or {}
        conflict = _conflict_set(pack, card.get("conflict_set_ref"))
        dominance = _dominance_policy(pack, conflict.get("dominance_policy_ref")) if conflict else None
        payload = {
            "text": card.get("claim_text") or card.get("id"),
            "source_trust": card.get("source_trust"),
            "object_status": card.get("object_status"),
            "scalar_basis_ref": card.get("scalar_basis_ref"),
            "scalar_basis_status": scalar.get("basis_status") if scalar else None,
            "temporal_status": card.get("temporal_status"),
            "blocked_use": card.get("blocked_use") or [],
        }
        candidates.append({
            "card_id": card.get("id"),
            "doc_id": card.get("source_ref") or card.get("source_version_ref") or card.get("id"),
            "title": card.get("id"),
            "path": card.get("source_ref") or "",
            "snippet": card.get("claim_text") or "",
            "text": card.get("claim_text") or "",
            "chunk_type": "plane_card",
            "plane": card.get("plane"),
            "authority_state": authority.get("bootstrap_state"),
            "status": card.get("object_status"),
            "canonical_layer": card.get("plane"),
            "payload": payload,
            "authority": {
                **authority,
                "state": authority.get("bootstrap_state"),
                "blocked_use": card.get("blocked_use") or [],
            },
            "blocked_use": card.get("blocked_use") or [],
            "allowed_use": card.get("allowed_use") or [],
            "temporal_status": card.get("temporal_status"),
            "valid_until": card.get("valid_until"),
            "source_trust": card.get("source_trust"),
            "object_status": card.get("object_status"),
            "authority_ref": card.get("authority_ref"),
            "scalar_basis_ref": card.get("scalar_basis_ref"),
            "state_vector": state,
            "conflict_set_ref": card.get("conflict_set_ref"),
            "dominance_policy_ref": dominance.get("id") if dominance else None,
            "conflicts": [conflict] if conflict else [],
            "eligibility": {"allowed": True, "reason": "fixture_candidate"},
        })
    return candidates


def compare_gate_result(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    return planar_gate.compare_expected_actual(expected or {}, actual or {})


def evaluate_fixture_case(
    case: dict[str, Any],
    pack: dict[str, Any],
    emit_mistake: bool = False,
) -> dict[str, Any]:
    candidates = candidate_packs_from_fixture_case(case, pack)
    actor = actor_from_pack(pack, case.get("actor_id") or (case.get("context_pack") or {}).get("actor") or "")
    context, actual_gate_result = planar_gate.evaluate_context_pack(
        query=(case.get("context_pack") or {}).get("query") or case.get("purpose") or case.get("id"),
        operation=case.get("operation") or (case.get("context_pack") or {}).get("operation") or "answer_context",
        actor=actor,
        mode="strict_answer",
        candidate_packs=candidates,
        governance_health=governance_health_from_pack(case, pack),
    )
    expected = case.get("expected_gate_result") or {}
    comparison = compare_gate_result(expected, actual_gate_result)
    mistake_event = None
    if emit_mistake and not comparison["passed"]:
        from app.core import correction_ledger

        mistake_event = correction_ledger.record_mistake_event(
            detected_from="fixture",
            operation=case.get("operation") or "answer_context",
            actor_ref=actor.get("actor_id") or "",
            query_ref=case.get("id"),
            context_pack_ref=context["context_pack_id"],
            expected_gate_result_ref=f"expected_gate_result:{case.get('id')}",
            actual_gate_result_ref=actual_gate_result["gate_result_id"],
            mistake_class=(expected.get("mistake_class") or case.get("family") or "fixture_mismatch"),
            impacted_refs=[c.get("card_id") for c in candidates if c.get("card_id")],
            severity="medium",
            detail={"mismatches": comparison["mismatches"], "fixture_id": case.get("id")},
        )
    return {
        "fixture_id": case.get("id"),
        "family": case.get("family"),
        "passed": comparison["passed"],
        "expected": expected,
        "actual": actual_gate_result,
        "context_pack": context,
        "mismatches": comparison["mismatches"],
        "mistake_event": mistake_event,
    }


def evaluate_fixture_pack(pack: dict[str, Any], emit_mistake: bool = False) -> dict[str, Any]:
    results = [evaluate_fixture_case(case, pack, emit_mistake=emit_mistake) for case in pack.get("fixture_cases", [])]
    families = sorted({r["family"] for r in results if r.get("family")})
    return {
        "fixture_pack_id": pack.get("fixture_pack_id"),
        "count": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "families": families,
        "results": results,
    }


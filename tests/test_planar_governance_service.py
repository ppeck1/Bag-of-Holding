"""Acceptance tests for the PlanarGovernanceService facade (Phase 5 / TASK 1.2).

The facade composes existing evaluators; these tests verify the aggregation is
deterministic, read-only, surfaces every posture, and never grants canon.
"""

from app.core import planar_gate
from app.core.planar_governance_service import GovernanceDecision, evaluate


def _pack(**overrides):
    pack = {
        "card_id": "card-1",
        "doc_id": "doc-1",
        "plane": "objective",
        "authority_state": "approved",
        "source_trust": "local",
        "scalar_basis_ref": "sb-1",
        "why_selected": {"semantic_score": 0.9},
    }
    pack.update(overrides)
    return pack


def _answerable():
    return evaluate(
        "reader",
        query="q",
        operation="answer_context",
        mode="exploration",
        candidate_packs=[_pack()],
    )


# ---------------------------------------------------------------------------
# Posture visibility (acceptance #4) -- bounded / review_required / blocked
# ---------------------------------------------------------------------------

def test_blocked_posture_when_role_denied():
    # A reader attempting to promote is role-denied -> blocking -> blocked.
    d = evaluate(
        "reader",
        query="q",
        operation="promote",
        mode="strict",
        candidate_packs=[_pack()],
    )
    assert d.posture == "blocked"
    assert d.allowed is False
    assert "actor_role_operation_denied" in d.blocking_reasons


def test_bounded_posture_when_warning_only():
    # Subjective card in a non-strict mode -> warning, no blocking -> bounded.
    d = evaluate(
        "reader",
        query="q",
        operation="answer_context",
        mode="exploration",
        candidate_packs=[_pack(plane="subjective")],
    )
    assert d.posture == "bounded"
    assert "subjective_card" in d.warning_reasons


def test_review_required_posture_when_route_without_blocking():
    # blocked_use on a non-high-risk op routes to review without blocking.
    d = evaluate(
        "reader",
        query="q",
        operation="explain",
        mode="exploration",
        candidate_packs=[_pack(blocked_use=["explain"])],
    )
    assert d.posture == "review_required"
    assert not d.blocking_reasons


def test_all_three_governed_postures_reachable():
    postures = set()
    postures.add(
        evaluate("reader", query="q", operation="promote", mode="strict",
                 candidate_packs=[_pack()]).posture
    )
    postures.add(
        evaluate("reader", query="q", operation="answer_context", mode="exploration",
                 candidate_packs=[_pack(plane="subjective")]).posture
    )
    postures.add(
        evaluate("reader", query="q", operation="explain", mode="exploration",
                 candidate_packs=[_pack(blocked_use=["explain"])]).posture
    )
    assert {"blocked", "bounded", "review_required"} <= postures


# ---------------------------------------------------------------------------
# Withheld context (acceptance #3)
# ---------------------------------------------------------------------------

def test_withheld_context_surfaced_separately_from_allowed():
    # promote + missing scalar basis withholds the pack.
    d = evaluate(
        "domain_owner",
        query="q",
        operation="promote",
        mode="strict",
        candidate_packs=[_pack(scalar_basis_ref=None)],
    )
    assert "scalar_basis_missing" in d.blocking_reasons
    assert d.withheld_context_refs
    # Allowed and withheld are disjoint.
    assert not (set(d.allowed_context_refs) & set(d.withheld_context_refs))


# ---------------------------------------------------------------------------
# Facade agrees with the underlying gate (acceptance #1)
# ---------------------------------------------------------------------------

def test_facade_posture_matches_planar_gate():
    pack = _pack(plane="subjective")
    _ctx, gate = planar_gate.evaluate_context_pack(
        query="q", operation="answer_context", actor="reader",
        mode="exploration", candidate_packs=[pack],
    )
    d = evaluate("reader", query="q", operation="answer_context",
                 mode="exploration", candidate_packs=[pack])
    assert d.posture == gate["posture"]
    assert d.gate_result_id == gate["gate_result_id"]


# ---------------------------------------------------------------------------
# No auto-canon mutation (acceptance #2)
# ---------------------------------------------------------------------------

def test_decision_never_canon_eligible():
    d = _answerable()
    assert d.canon_eligible is False
    assert d.to_dict()["canon_eligible"] is False


def test_decision_forced_non_canon_even_if_set():
    d = GovernanceDecision(
        operation="x", posture="answerable", allowed=True,
        context_pack_id="c", gate_result_id="g", trace_event_type="gate_passed",
        canon_eligible=True,  # type: ignore[call-arg]
    )
    assert d.canon_eligible is False


def test_evaluate_performs_no_db_writes(monkeypatch):
    # If the facade tried to write, this would raise. It reads no DB itself.
    import app.db.connection as db

    def _boom(*a, **k):
        raise AssertionError("governance facade must not execute SQL")

    monkeypatch.setattr(db, "execute", _boom, raising=False)
    monkeypatch.setattr(db, "executemany", _boom, raising=False)
    d = _answerable()
    assert d.posture in {"answerable", "bounded", "review_required", "blocked"}


# ---------------------------------------------------------------------------
# Determinism (acceptance #6)
# ---------------------------------------------------------------------------

def test_facade_is_deterministic():
    a = _answerable()
    b = _answerable()
    assert a.to_dict() == b.to_dict()
    assert a.decision_id == b.decision_id


def test_decision_id_changes_with_transition():
    base = evaluate("reader", query="q", operation="answer_context", mode="exploration",
                    candidate_packs=[_pack()])
    with_tx = evaluate("reader", query="q", operation="answer_context", mode="exploration",
                       candidate_packs=[_pack()], transition=("draft", "review_required"))
    assert base.decision_id != with_tx.decision_id


# ---------------------------------------------------------------------------
# Composed sub-evaluators surfaced in the decision
# ---------------------------------------------------------------------------

def test_authority_decision_surfaced_when_card_supplied():
    card = {"id": "card-1", "plane": "objective", "payload": {}, "valid_until": None}
    d = evaluate("reader", query="q", operation="explain", mode="exploration",
                 candidate_packs=[_pack()], card=card)
    assert d.authority is not None
    assert "allowed" in d.authority


def test_transition_result_surfaced_when_requested():
    d = evaluate("reader", query="q", operation="answer_context", mode="exploration",
                 candidate_packs=[_pack()], transition=("draft", "canonical"))
    # canonical promotion without approved=True is rejected.
    assert d.transition_ok is False
    assert "approval" in (d.transition_reason or "").lower()


def test_conflicts_injected_are_counted():
    d = evaluate("reader", query="q", operation="answer_context", mode="exploration",
                 candidate_packs=[_pack()],
                 conflicts=[{"conflict_id": "cf-1"}, {"id": "cf-2"}])
    assert d.conflict_count == 2
    assert sorted(d.conflict_ids) == ["cf-1", "cf-2"]

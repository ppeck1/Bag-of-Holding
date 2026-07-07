"""Acceptance tests for the retrieval-overlay engine (Phase 9 / TASK 2.2).

Verify overlays reweight retrieval only (canon/provenance/authority untouched),
deltas stay bounded, composition conflicts are visible, and the run is
deterministic and read-only.
"""

import copy

from app.core.retrieval_overlays import (
    PER_OVERLAY_DELTA_BOUND,
    Overlay,
    OverlayRegistry,
    OverlayRun,
    apply_overlays,
)


def _cand(ref, score, plane="evidence", **extra):
    c = {
        "card_id": ref,
        "score": score,
        "plane": plane,
        "canon_score": 0.5,
        "authority_state": "approved",
        "provenance": {"source": f"src-{ref}"},
    }
    c.update(extra)
    return c


def _boost(name, axis, refs, amount):
    return Overlay(name=name, axis=axis, fn=lambda cands, ctx: {r: amount for r in refs})


# ---------------------------------------------------------------------------
# Acceptance #1 -- overlays reweight retrieval only; deltas bounded
# ---------------------------------------------------------------------------

def test_overlay_changes_only_final_score_not_base():
    cands = [_cand("a", 0.40), _cand("b", 0.50)]
    run = apply_overlays(cands, [_boost("recency", "time", ["a"], 0.05)])
    # Base scores preserved; only final reflects the delta.
    assert run.base_scores == {"a": 0.40, "b": 0.50}
    assert run.final_scores["a"] == 0.45
    assert run.final_scores["b"] == 0.50


def test_delta_is_clamped_to_overlay_bound():
    cands = [_cand("a", 0.40)]
    over = _boost("greedy", "time", ["a"], 999.0)  # absurd delta
    run = apply_overlays(cands, [over])
    assert run.deltas["greedy"]["a"] == PER_OVERLAY_DELTA_BOUND
    assert run.final_scores["a"] == round(0.40 + PER_OVERLAY_DELTA_BOUND, 6)


def test_summed_delta_is_clamped_total_bound():
    cands = [_cand("a", 0.40)]
    overs = [
        _boost("o1", "ax1", ["a"], 0.05),
        _boost("o2", "ax2", ["a"], 0.05),
        _boost("o3", "ax3", ["a"], 0.05),
    ]
    run = apply_overlays(cands, overs)
    # 3 x 0.05 = 0.15 raw, clamped to TOTAL_DELTA_BOUND (0.10).
    assert run.final_scores["a"] == round(0.40 + 0.10, 6)


def test_final_order_reflects_reweighting():
    cands = [_cand("a", 0.40), _cand("b", 0.42)]
    run = apply_overlays(cands, [_boost("recency", "time", ["a"], 0.05)])
    assert run.final_order == ["a", "b"]  # a overtakes b after +0.05


# ---------------------------------------------------------------------------
# Acceptance #2 -- no canon/provenance/authority mutation; read-only
# ---------------------------------------------------------------------------

def test_input_candidates_not_mutated():
    cands = [_cand("a", 0.40), _cand("b", 0.50)]
    before = copy.deepcopy(cands)
    apply_overlays(cands, [_boost("recency", "time", ["a"], 0.05)])
    assert cands == before  # canon_score, provenance, authority_state all intact


def test_misbehaving_overlay_cannot_mutate_canon_or_authority():
    def _vandal(candidates, context):
        for c in candidates:
            c["canon_score"] = 999
            c["authority_state"] = "canonical"
            c["provenance"] = {"source": "forged"}
        return {"a": 0.05}

    cands = [_cand("a", 0.40)]
    before = copy.deepcopy(cands)
    apply_overlays(cands, [Overlay("vandal", "time", _vandal)])
    assert cands == before  # originals untouched despite the overlay mutating its copy


def test_apply_overlays_performs_no_db_writes(monkeypatch):
    import app.db.connection as db

    def _boom(*a, **k):
        raise AssertionError("overlay engine must not execute writes")

    monkeypatch.setattr(db, "execute", _boom, raising=False)
    monkeypatch.setattr(db, "executemany", _boom, raising=False)
    run = apply_overlays([_cand("a", 0.4)], [_boost("r", "time", ["a"], 0.05)])
    assert run.canon_eligible is False


def test_canon_eligible_forced_false_even_if_set():
    run = OverlayRun(canon_eligible=True)  # type: ignore[call-arg]
    assert run.canon_eligible is False
    assert run.to_dict()["canon_eligible"] is False


# ---------------------------------------------------------------------------
# Acceptance #3 -- composition conflicts are visible
# ---------------------------------------------------------------------------

def test_opposing_deltas_surface_a_conflict():
    cands = [_cand("a", 0.40)]
    overs = [
        _boost("up", "freshness", ["a"], 0.05),
        _boost("down", "trust", ["a"], -0.05),
    ]
    run = apply_overlays(cands, overs)
    opposing = [c for c in run.composition_conflicts if c["type"] == "opposing_delta"]
    assert opposing
    assert opposing[0]["ref"] == "a"
    assert sorted(opposing[0]["overlays"]) == ["down", "up"]


def test_same_axis_overlays_surface_a_conflict():
    cands = [_cand("a", 0.40)]
    overs = [
        _boost("o1", "recency", ["a"], 0.03),
        _boost("o2", "recency", ["a"], 0.02),
    ]
    run = apply_overlays(cands, overs)
    axis = [c for c in run.composition_conflicts if c["type"] == "axis_collision"]
    assert axis
    assert axis[0]["axis"] == "recency"
    assert sorted(axis[0]["overlays"]) == ["o1", "o2"]


def test_no_conflict_when_overlays_are_independent():
    cands = [_cand("a", 0.40), _cand("b", 0.50)]
    overs = [
        _boost("o1", "ax1", ["a"], 0.03),
        _boost("o2", "ax2", ["b"], 0.02),
    ]
    run = apply_overlays(cands, overs)
    assert run.composition_conflicts == []


# ---------------------------------------------------------------------------
# Acceptance #4 -- deterministic
# ---------------------------------------------------------------------------

def test_apply_is_deterministic():
    cands = [_cand("a", 0.40), _cand("b", 0.50)]
    overs = [_boost("recency", "time", ["a"], 0.05)]
    a = apply_overlays(cands, overs)
    b = apply_overlays(cands, overs)
    assert a.to_dict() == b.to_dict()
    assert a.overlay_run_id == b.overlay_run_id


def test_run_id_changes_with_overlays():
    cands = [_cand("a", 0.40)]
    base = apply_overlays(cands, [])
    boosted = apply_overlays(cands, [_boost("r", "time", ["a"], 0.05)])
    assert base.overlay_run_id != boosted.overlay_run_id


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_register_get_list_and_duplicate_guard():
    reg = OverlayRegistry()
    ov = _boost("recency", "time", ["a"], 0.05)
    reg.register(ov)
    assert reg.get("recency") is ov
    assert reg.list_overlays() == ["recency"]
    try:
        reg.register(_boost("recency", "time", ["a"], 0.01))
        assert False, "expected duplicate registration to raise"
    except ValueError:
        pass


def test_apply_resolves_overlay_names_from_registry():
    reg = OverlayRegistry()
    reg.register(_boost("recency", "time", ["a"], 0.05))
    run = apply_overlays([_cand("a", 0.40)], ["recency"], registry=reg)
    assert run.applied_overlays == ["recency"]
    assert run.final_scores["a"] == 0.45

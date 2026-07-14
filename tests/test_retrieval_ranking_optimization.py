"""RQ-4 test-first gates for retained retrieval ranking hypotheses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.probes import retrieval_quality_baseline_v0_1 as baseline


DECK_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "retrieval_quality"
    / "judged_deck_v0_1.json"
)
FROZEN_BASELINE_PATH = Path(__file__).parents[1] / "docs" / "retrieval" / "RETRIEVAL_BASELINE_v0_1.json"
PRIVATE_ADAPTER_PATH = (
    Path(__file__).parents[1] / "tools" / "boh_mcp_adapter" / "adapter.py"
)


def _require_operational_mcp_adapter() -> None:
    if not PRIVATE_ADAPTER_PATH.is_file():
        pytest.skip("operational MCP adapter is excluded from the sanitized export")


@pytest.fixture
def synthetic_fixture():
    deck, _digest = baseline.load_deck(DECK_PATH)
    with baseline._temporary_fixture(deck) as db:
        with baseline._measurement_state(baseline._epoch(deck["as_of"])):
            yield deck, db


def _case(deck: dict, case_id: str) -> dict:
    return next(case for case in deck["cases"] if case["case_id"] == case_id)


def test_retrieval_authority_signal_stays_inside_its_component_budget():
    from app.core import retrieval

    strongest = retrieval._authority_weight({
        "status": "canonical",
        "authority_state": "approved",
        "canonical_layer": "canonical",
    })
    weakest = retrieval._authority_weight({
        "status": "draft",
        "authority_state": "draft",
        "canonical_layer": "supporting",
    })

    assert strongest == pytest.approx(0.15)
    assert weakest == pytest.approx(-0.08)


def test_exploration_relevance_is_not_overwhelmed_by_approved_decoy_authority(
    synthetic_fixture,
):
    deck, _db = synthetic_fixture
    case = _case(deck, "promoted_only_01_open")
    from app.core import retrieval

    with baseline._promoted_gate(True):
        result = retrieval.retrieve_governed(
            case["query"],
            mode=case["mode"],
            limit=5,
            filters=case["filters"],
            include_promoted=True,
        )

    assert result["context_packs"][0]["doc_id"] == "doc-promoted-lattice"
    scores = {pack["doc_id"]: pack["score"] for pack in result["context_packs"]}
    if "doc-promoted-decoy" in scores:
        assert scores["doc-promoted-lattice"] > scores["doc-promoted-decoy"]
    assert result["context_packs"][0]["do_not_treat_as_canonical"] is True


def test_promoted_rank_change_never_bypasses_visibility_or_strict_authority(
    synthetic_fixture,
):
    deck, _db = synthetic_fixture
    case = _case(deck, "promoted_only_01_open")
    from app.core import retrieval

    with baseline._promoted_gate(False):
        server_closed = retrieval.retrieve_governed(
            case["query"], mode="exploration", limit=5, include_promoted=True
        )
    with baseline._promoted_gate(True):
        request_closed = retrieval.retrieve_governed(
            case["query"], mode="exploration", limit=5, include_promoted=False
        )
        strict = retrieval.retrieve_governed(
            case["query"], mode="strict_answer", limit=5, include_promoted=True
        )

    assert "doc-promoted-lattice" not in {
        pack["doc_id"] for pack in server_closed["context_packs"]
    }
    assert "doc-promoted-lattice" not in {
        pack["doc_id"] for pack in request_closed["context_packs"]
    }
    assert "doc-promoted-lattice" not in {
        pack["doc_id"] for pack in strict["context_packs"]
    }
    assert any(
        item.get("doc_id") == "doc-promoted-lattice"
        and item.get("reason") == "missing_plane_card"
        for item in strict["excluded_summary"]
    )


def test_authority_normalization_improves_judged_ranking_without_regression():
    _require_operational_mcp_adapter()
    from app.core import retrieval

    report, _timing = baseline.run_baseline(DECK_PATH, timing_iterations=0)
    frozen = json.loads(FROZEN_BASELINE_PATH.read_text(encoding="utf-8"))
    evaluated = report["evaluations"]["api_retrieve"]
    metrics = evaluated["metrics"]

    assert metrics["recall_at_5"] >= 0.933333
    assert metrics["mrr"] == 1.0
    assert metrics["ndcg_at_5"] >= 0.950311
    assert metrics["exact_phrase_top1_accuracy"] == 1.0
    assert metrics["no_answer_false_positive_rate"] == 0.0
    assert metrics["top_k_prefix_stability"] == 1.0
    assert metrics["authority_posture"]["match_rate"] >= 0.708333
    assert metrics["freshness_posture"]["match_rate"] >= 0.791667
    assert metrics["sql_read_statements"]["p50"] <= 4
    assert metrics["sql_read_statements"]["p95"] <= 8
    assert evaluated["failure_counts"]["wrong_top_result"] == 1
    assert all(
        group["leaked_results"] == 0
        for group in metrics["policy_boundary_leakage"].values()
    )

    failures_by_code = {}
    for failure in evaluated["failures"]:
        failures_by_code.setdefault(failure["code"], set()).add(failure["case_id"])
    assert failures_by_code["wrong_top_result"] == {
        "conflict_supersession_03_helios_history"
    }
    assert failures_by_code["forbidden_relevance_hit"] <= {
        "exact_phrase_01_cobalt",
        "exact_phrase_02_orchid",
        "exact_phrase_03_river",
        "identifier_lookup_02_aurelia42",
        "natural_question_01_cedar",
        "natural_question_02_lyra",
        "natural_question_03_finch",
        "promoted_only_01_open",
        "promoted_only_02_request_closed",
        "promoted_only_03_server_closed",
    }
    assert failures_by_code["answerability_mismatch"] <= {
        "promoted_only_02_request_closed",
        "promoted_only_03_server_closed",
        "strict_disallowed_02_draft",
        "strict_disallowed_03_expired",
        "stale_current_02_historical",
    }
    assert failures_by_code["withheld_reason_missing"] <= {
        "promoted_only_02_request_closed",
        "promoted_only_03_server_closed",
        "strict_disallowed_02_draft",
    }

    old_observations = {
        item["case_id"]: item for item in frozen["observations"]["api_retrieve"]
    }
    new_observations = {
        item["case_id"]: item for item in report["observations"]["api_retrieve"]
    }
    deck, _digest = baseline.load_deck(DECK_PATH)
    strong_identifier_cases = {
        case["case_id"]
        for case in deck["cases"]
        if retrieval._strong_identifier_terms(retrieval._terms(case["query"]))
    }
    for case_id, old in old_observations.items():
        if case_id in strong_identifier_cases or not old["applicable"]:
            continue
        old_top = old["results"][0]["doc_id"] if old["results"] else None
        new_top = (
            new_observations[case_id]["results"][0]["doc_id"]
            if new_observations[case_id]["results"] else None
        )
        assert new_top == old_top, case_id


def test_strong_identifier_lane_excludes_generic_decoys(synthetic_fixture):
    deck, _db = synthetic_fixture
    from app.core import retrieval

    cases = {
        case_id: _case(deck, case_id)
        for case_id in (
            "identifier_lookup_01_kx17",
            "identifier_lookup_02_aurelia42",
            "identifier_lookup_03_receipt42",
            "promoted_only_01_open",
            "no_answer_02_identifier",
        )
    }
    with baseline._promoted_gate(True):
        results = {
            case_id: retrieval.retrieve_governed(
                case["query"],
                mode=case["mode"],
                limit=5,
                filters=case["filters"],
                include_promoted=bool(case["exposure"]["request_include_promoted"]),
            )
            for case_id, case in cases.items()
        }

    assert [pack["doc_id"] for pack in results["identifier_lookup_01_kx17"]["context_packs"]] == [
        "doc-id-kx17"
    ]
    assert [pack["doc_id"] for pack in results["identifier_lookup_02_aurelia42"]["context_packs"]] == [
        "doc-id-aurelia42"
    ]
    assert [pack["doc_id"] for pack in results["identifier_lookup_03_receipt42"]["context_packs"]] == [
        "doc-id-receipt42"
    ]
    assert [pack["doc_id"] for pack in results["promoted_only_01_open"]["context_packs"]] == [
        "doc-promoted-lattice"
    ]
    assert results["no_answer_02_identifier"]["context_packs"] == []


def test_hidden_strong_identifier_does_not_fall_back_to_generic_false_answer(
    synthetic_fixture,
):
    deck, _db = synthetic_fixture
    from app.core import retrieval

    request_closed_case = _case(deck, "promoted_only_02_request_closed")
    server_closed_case = _case(deck, "promoted_only_03_server_closed")
    with baseline._promoted_gate(True):
        request_closed = retrieval.retrieve_governed(
            request_closed_case["query"],
            mode=request_closed_case["mode"],
            limit=5,
            include_promoted=False,
        )
    with baseline._promoted_gate(False):
        server_closed = retrieval.retrieve_governed(
            server_closed_case["query"],
            mode=server_closed_case["mode"],
            limit=5,
            include_promoted=True,
        )

    assert request_closed["context_packs"] == []
    assert server_closed["context_packs"] == []
    assert request_closed["gate_result"]["allowed_context_refs"] == []
    assert server_closed["gate_result"]["allowed_context_refs"] == []


def test_strong_identifier_lane_improves_false_answer_and_forbidden_diagnostics():
    _require_operational_mcp_adapter()
    report, _timing = baseline.run_baseline(DECK_PATH, timing_iterations=0)
    evaluated = report["evaluations"]["api_retrieve"]
    metrics = evaluated["metrics"]

    assert evaluated["failure_counts"]["forbidden_relevance_hit"] <= 6
    assert evaluated["failure_counts"]["answerability_mismatch"] <= 3
    assert metrics["expected_unanswerable_false_positive_rate"] <= 0.333333
    assert metrics["recall_at_5"] >= 0.933333
    assert metrics["mrr"] == 1.0
    assert metrics["ndcg_at_5"] >= 0.950311
    assert metrics["top_k_prefix_stability"] == 1.0
    assert metrics["sql_read_statements"]["p50"] <= 4
    assert metrics["sql_read_statements"]["p95"] <= 8
    assert all(
        group["leaked_results"] == 0
        for group in metrics["policy_boundary_leakage"].values()
    )

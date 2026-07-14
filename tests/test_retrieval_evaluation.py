from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.core import retrieval_evaluation as evaluation


DECK_PATH = Path(__file__).parent / "fixtures" / "retrieval_quality" / "judged_deck_v0_1.json"


def _deck():
    return json.loads(DECK_PATH.read_text(encoding="utf-8"))


def _perfect_observations(deck):
    observations = []
    for case in deck["cases"]:
        expected = case["expected"]
        if expected["answerable"] and expected["graded_relevance"]:
            ranked = sorted(expected["graded_relevance"], key=lambda item: item["grade"], reverse=True)
            results = [
                {"doc_id": item["doc_id"], "chunk_id": item["chunk_id"]}
                for item in ranked
                if item["doc_id"] not in expected["forbidden_doc_ids"]
            ]
        else:
            results = []
        observations.append({
            "case_id": case["case_id"],
            "results": results,
            "answerable": expected["answerable"],
            "withheld_reasons": expected["withheld_reasons"],
            "sql_read_statements": 4,
            "elapsed_ms": 2.0,
            "limit_results": {"3": results[:3], "5": results[:5]},
        })
    return observations


def test_versioned_deck_is_complete_and_resolvable():
    deck = _deck()
    evaluation.validate_deck(deck)
    assert len(deck["documents"]) == 31
    assert len(deck["cases"]) == 30
    assert {case["category"] for case in deck["cases"]} == set(evaluation.REQUIRED_CATEGORIES)


def test_validation_rejects_missing_category_coverage():
    deck = _deck()
    deck["cases"] = [case for case in deck["cases"] if case["category"] != "exact_phrase"]
    with pytest.raises(evaluation.DeckValidationError, match="at least 30|exact_phrase"):
        evaluation.validate_deck(deck)


def test_validation_rejects_unsafe_fixture_path():
    deck = _deck()
    deck["documents"][0]["path"] = "../real-library/private.md"
    with pytest.raises(evaluation.DeckValidationError, match="unsafe fixture path"):
        evaluation.validate_deck(deck)


def test_relevant_forbidden_overlap_is_valid_policy_judgment():
    deck = _deck()
    case = next(case for case in deck["cases"] if case["case_id"] == "strict_disallowed_01_subjective")
    assert case["expected"]["graded_relevance"][0]["doc_id"] in case["expected"]["forbidden_doc_ids"]
    evaluation.validate_deck(deck)


def test_metrics_have_hand_checkable_perfect_values():
    deck = _deck()
    report = evaluation.evaluate_observations(deck, _perfect_observations(deck))
    assert report["metrics"]["recall_at_5"] == 1.0
    assert report["metrics"]["mrr"] == 1.0
    assert report["metrics"]["ndcg_at_5"] == 1.0
    assert report["metrics"]["exact_phrase_top1_accuracy"] == 1.0
    assert report["metrics"]["no_answer_false_positive_rate"] == 0.0
    assert report["metrics"]["top_k_prefix_stability"] == 1.0
    assert report["metrics"]["sql_read_statements"] == {
        "sample_count": 30,
        "total": 120,
        "p50": 4.0,
        "p95": 4.0,
    }
    assert report["passed"] is True


def test_wrong_top_fault_injection_fails_relevance_gate_only():
    deck = _deck()
    observations = _perfect_observations(deck)
    observation = next(item for item in observations if item["case_id"] == "exact_phrase_01_cobalt")
    observation["results"].insert(0, {"doc_id": "doc-id-kx17", "chunk_id": "chunk-id-kx17-0"})
    report = evaluation.evaluate_observations(deck, observations)
    assert report["gates"]["relevance_gate_passed"] is False
    assert report["gates"]["boundary_gate_passed"] is True
    assert any(item["code"] == "wrong_top_result" for item in report["failures"])
    assert report["passed"] is False


def test_forbidden_boundary_fault_injection_fails_boundary_gate():
    deck = _deck()
    observations = _perfect_observations(deck)
    observation = next(item for item in observations if item["case_id"] == "strict_disallowed_01_subjective")
    observation["results"] = [{"doc_id": "doc-strict-subjective", "chunk_id": "chunk-strict-subjective-0"}]
    report = evaluation.evaluate_observations(deck, observations)
    assert report["gates"]["boundary_gate_passed"] is False
    assert report["metrics"]["policy_boundary_leakage"]["authority"]["leaked_results"] == 1
    assert any(item["code"] == "policy_boundary_leak" for item in report["failures"])
    assert report["passed"] is False


def test_prefix_instability_is_measured_without_wall_clock_gate():
    deck = _deck()
    observations = _perfect_observations(deck)
    observation = next(item for item in observations if item["case_id"] == "exact_phrase_01_cobalt")
    expected = observation["results"][0]
    decoy = {"doc_id": "doc-id-kx17", "chunk_id": "chunk-id-kx17-0"}
    observation["limit_results"] = {"3": [expected], "5": [decoy, expected]}
    report = evaluation.evaluate_observations(deck, observations)
    assert report["metrics"]["top_k_prefix_stability"] < 1.0
    assert report["metrics"]["elapsed_ms"]["p50"] == 2.0


def test_not_applicable_observations_are_retained_but_not_scored():
    deck = _deck()
    observations = _perfect_observations(deck)
    observations[0] = {
        "case_id": observations[0]["case_id"],
        "applicable": False,
        "not_applicable_reason": "surface_has_no_strict_mode",
        "results": [],
    }
    report = evaluation.evaluate_observations(deck, observations)
    assert report["not_applicable_count"] == 1
    assert report["not_applicable_reasons"] == {"surface_has_no_strict_mode": 1}
    assert report["scored_case_count"] == 29
    assert report["metrics"]["sql_read_statements"]["sample_count"] == 29


def test_not_applicable_boundary_exposure_is_characterized_without_becoming_a_gate_failure():
    deck = _deck()
    observations = _perfect_observations(deck)
    target = next(item for item in observations if item["case_id"] == "daenary_private_03_private")
    target.update({
        "applicable": False,
        "not_applicable_reason": "no_normalized_private_boundary",
        "results": [{"doc_id": "doc-private-ember", "chunk_id": "chunk-private-ember-0"}],
    })
    report = evaluation.evaluate_observations(deck, observations)
    private = report["metrics"]["observed_forbidden_exposure_all_cases"]["private_unmodeled"]
    assert private["exposed_cases"] == 1
    assert private["case_ids"] == ["daenary_private_03_private"]
    assert report["gates"]["boundary_gate_passed"] is True


def test_percentile_uses_nearest_rank():
    assert evaluation.percentile([1, 2, 3, 4], 50) == 2.0
    assert evaluation.percentile([1, 2, 3, 4], 95) == 4.0
    assert evaluation.percentile([], 50) is None


def test_duplicate_judged_hits_cannot_raise_ndcg_above_one():
    deck = _deck()
    observations = _perfect_observations(deck)
    target = next(item for item in observations if item["case_id"] == "exact_phrase_01_cobalt")
    judged = target["results"][0]
    target["results"] = [dict(judged) for _ in range(5)]
    report = evaluation.evaluate_observations(deck, observations)
    assert 0.0 <= report["metrics"]["ndcg_at_5"] <= 1.0


def test_no_answer_rate_is_separate_from_all_expected_unanswerable_cases():
    deck = _deck()
    observations = _perfect_observations(deck)
    target = next(item for item in observations if item["case_id"] == "promoted_only_02_request_closed")
    target["answerable"] = True
    report = evaluation.evaluate_observations(deck, observations)
    assert report["metrics"]["no_answer_false_positive_rate"] == 0.0
    assert report["metrics"]["expected_unanswerable_false_positive_rate"] > 0.0


def test_observation_validation_rejects_negative_sql_statement_count():
    deck = _deck()
    observations = _perfect_observations(deck)
    observations[0]["sql_read_statements"] = -1
    with pytest.raises(ValueError, match="sql_read_statements"):
        evaluation.evaluate_observations(deck, observations)


def test_nested_limit_results_are_validated_fail_closed():
    deck = _deck()
    observations = _perfect_observations(deck)
    observations[0]["limit_results"]["3"] = [
        {"doc_id": "doc-phrase-cobalt", "chunk_id": "chunk-id-kx17-0"}
    ]
    with pytest.raises(ValueError, match=r"limit_results\[3\].*mismatch"):
        evaluation.evaluate_observations(deck, observations)


def test_required_withheld_reason_is_a_distinct_gate():
    deck = _deck()
    observations = _perfect_observations(deck)
    target = next(item for item in observations if item["case_id"] == "strict_disallowed_01_subjective")
    target["withheld_reasons"] = []
    report = evaluation.evaluate_observations(deck, observations)
    assert report["gates"]["withholding_passed"] is False
    assert any(item["code"] == "withheld_reason_missing" for item in report["failures"])


def test_authority_and_freshness_posture_checks_are_reported_when_supported():
    deck = _deck()
    observations = _perfect_observations(deck)
    target = next(item for item in observations if item["case_id"] == "exact_phrase_01_cobalt")
    target["results"][0].update({
        "status": "canonical",
        "authority_state": "approved",
        "canonical_layer": "canonical",
        "freshness": {"age_days": 9, "superseded": False},
    })
    report = evaluation.evaluate_observations(deck, observations)
    check = next(item for item in report["posture_checks"] if item["case_id"] == target["case_id"])
    assert check["authority_match"] is True
    assert check["freshness_match"] is True
    assert report["metrics"]["authority_posture"]["supported_cases"] > 0
    assert report["metrics"]["freshness_posture"]["supported_cases"] > 0


def test_missing_observation_fails_closed():
    deck = _deck()
    observations = _perfect_observations(deck)[:-1]
    with pytest.raises(ValueError, match="missing observations"):
        evaluation.evaluate_observations(deck, observations)


def test_temp_harness_is_repeatable_and_characterizes_surfaces_without_content(monkeypatch):
    adapter_path = (
        Path(__file__).parents[1] / "tools" / "boh_mcp_adapter" / "adapter.py"
    )
    if not adapter_path.is_file():
        pytest.skip("operational MCP adapter is excluded from the sanitized export")
    from tools.probes import retrieval_quality_baseline_v0_1 as baseline
    from app.core import retrieval
    from app.db import connection as db

    original_logger = retrieval.log_storage_event
    original_db_path = db.DB_PATH
    first, timing = baseline.run_baseline(DECK_PATH, timing_iterations=0)
    monkeypatch.setattr(baseline.time, "time", lambda: 4_102_444_800.0)
    second, _ = baseline.run_baseline(DECK_PATH, timing_iterations=0)

    assert retrieval.log_storage_event is original_logger
    assert db.DB_PATH == original_db_path
    assert baseline.canonical_json(first) == baseline.canonical_json(second)
    assert first["fixture"] == {
        "synthetic_only": True,
        "document_count": 31,
        "chunk_count": 32,
        "case_count": 30,
        "real_database_option_exposed": False,
    }
    assert first["as_of"] == "2026-07-10T12:00:00+00:00"
    assert first["surface_order"] == list(baseline.SURFACE_ORDER)
    assert first["interpretation"]["keyword_search_is_discovery"] is True
    assert first["surface_capabilities"]["keyword_search"]["role"] == "document_discovery"
    assert all(
        first["evaluations"][surface]["metrics"]["sql_read_statements"]["sample_count"] > 0
        for surface in baseline.SURFACE_ORDER
    )
    assert all(timing["surfaces"][surface]["sample_count"] == 0 for surface in baseline.SURFACE_ORDER)
    serialized = baseline.canonical_json(first)
    assert "The cobalt lantern protocol begins" not in serialized
    assert "emberglass magenta latch" not in serialized

"""RQ-3 test-first contract for one governed retrieval population.

The tests use only the frozen synthetic RQ-2 deck and a harness-owned temporary
database.  They intentionally describe the post-RQ-3 contract: before the
implementation lands, the normalized-result and supplied-result tests fail.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from tools.probes import retrieval_quality_baseline_v0_1 as baseline


DECK_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "retrieval_quality"
    / "judged_deck_v0_1.json"
)
PRIVATE_ADAPTER_PATH = (
    Path(__file__).parents[1] / "tools" / "boh_mcp_adapter" / "adapter.py"
)


def _require_operational_mcp_adapter() -> None:
    if not PRIVATE_ADAPTER_PATH.is_file():
        pytest.skip("operational MCP adapter is excluded from the sanitized export")

ESTABLISHED_RETRIEVE_KEYS = {
    "query",
    "count",
    "context_packs",
    "excluded_summary",
    "audit_context",
    "retrieval",
    "planar_context_pack",
    "gate_result",
    "warnings",
}
ESTABLISHED_BRIEF_KEYS = {
    "contract",
    "topic",
    "answerable_now",
    "current_context_summary",
    "newest_evidence",
    "best_evidence",
    "superseded_or_conflicted",
    "withheld",
    "unknowns",
    "warnings",
    "promoted_visibility",
    "retrieval",
    "llm_instructions",
}
ESTABLISHED_CONTEXT_KEYS = {
    "scope",
    "state",
    "evidence",
    "conflicts",
    "unknowns",
    "actions",
}
ESTABLISHED_MCP_KEYS = {
    "tool",
    "read_only",
    "query",
    "project",
    "promoted_visibility",
    "retrieval",
    "context_packs",
    "assembled_context_pack",
}


class GovernedStub(Mapping[str, Any]):
    """Minimal mapping-compatible normalized result supplied to consumers."""

    def __init__(self, payload: dict[str, Any]):
        self._payload = copy.deepcopy(payload)

    def __getitem__(self, key: str) -> Any:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._payload)


@pytest.fixture
def synthetic_fixture():
    deck, _digest = baseline.load_deck(DECK_PATH)
    with baseline._temporary_fixture(deck) as db:
        as_of_epoch = baseline._epoch(deck["as_of"])
        with baseline._measurement_state(as_of_epoch):
            yield deck, db


def _case(deck: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(case for case in deck["cases"] if case["case_id"] == case_id)


def _pack_ids(items: list[dict[str, Any]]) -> list[tuple[str | None, str | None]]:
    return [(item.get("doc_id"), item.get("chunk_id")) for item in items]


def _withheld_reasons(response: dict[str, Any]) -> set[str]:
    reasons: set[str] = set()
    for item in response.get("excluded_summary") or []:
        if item.get("reason"):
            reasons.add(str(item["reason"]))
    for item in response.get("withheld") or []:
        if isinstance(item, dict) and item.get("reason"):
            reasons.add(str(item["reason"]))
    gate = response.get("gate_result") or {}
    reasons.update(str(value) for value in gate.get("blocking_reasons") or [])
    assembled = response.get("assembled_context_pack") or {}
    declaration = assembled.get("withheld") or {}
    reasons.update(str(value) for value in declaration.get("reasons") or [])
    return reasons


def _governed_stub() -> GovernedStub:
    allowed = {
        "chunk_id": "chunk-shared-allowed-0",
        "card_id": "card-shared-allowed",
        "doc_id": "doc-shared-allowed",
        "title": "Synthetic allowed evidence",
        "path": "synthetic/shared/allowed.md",
        "snippet": "Synthetic allowed evidence.",
        "text": "Synthetic allowed evidence.",
        "heading_path": "Allowed",
        "chunk_type": "body",
        "source_span": {
            "byte_start": 0,
            "byte_end": 27,
            "token_start": 0,
            "token_end": 3,
        },
        "source_spans": [{"byte_start": 0, "byte_end": 27, "token_start": 0, "token_end": 3}],
        "citation_uri": "boh://doc-shared-allowed#chunk-shared-allowed-0",
        "citation": {
            "doc_id": "doc-shared-allowed",
            "chunk_id": "chunk-shared-allowed-0",
            "path": "synthetic/shared/allowed.md",
            "title": "Synthetic allowed evidence",
        },
        "score": 0.91,
        "authority_state": "approved",
        "status": "canonical",
        "canonical_layer": "canonical",
        "freshness": {"age_days": 1, "source": "epistemic_last_evaluated"},
        "provenance": {"source": "synthetic-rq3-test"},
        "intake_provenance": None,
        "conflicts": [],
        "lineage": [],
        "warnings": [],
        "why_selected": {"retrieval_source": "fts"},
        "do_not_treat_as_canonical": False,
        "eligibility": {"allowed": True, "reason": "allowed"},
        "plane": "canonical",
    }
    excluded = {
        "card_id": "card-shared-withheld",
        "doc_id": "doc-shared-withheld",
        "title": None,
        "plane": "subjective",
        "mode": "exploration",
        "reason": "policy_withheld_fixture",
        "required_action": "review_card",
        "visible_message": "Synthetic policy withholding.",
    }
    return GovernedStub(
        {
            "query": "shared governed fixture",
            "count": 1,
            "context_packs": [allowed],
            "excluded_summary": [excluded],
            "audit_context": {},
            "retrieval": {
                "mode": "hybrid_v1",
                "planar_mode": "exploration",
                "read_only": True,
                "returned_count": 1,
                "excluded_count": 1,
            },
            "planar_context_pack": {"context_pack_id": "ctx-shared"},
            "gate_result": {
                "gate_result_id": "gate-shared",
                "context_pack_id": "ctx-shared",
                "posture": "review_required",
                "blocking_reasons": [],
                "warning_reasons": ["policy_withheld_fixture"],
                "allowed_context_refs": ["card-shared-allowed"],
                "withheld_context_refs": ["card-shared-withheld"],
                "required_route": "review",
            },
            "warnings": ["policy_withheld_fixture"],
        }
    )


def test_normalized_governed_result_is_mapping_compatible_and_wire_deterministic(
    synthetic_fixture,
):
    deck, _db = synthetic_fixture
    case = _case(deck, "identifier_lookup_01_kx17")
    from app.core import retrieval

    result = retrieval.retrieve_governed_result(
        case["query"], mode=case["mode"], limit=5, filters=case["filters"]
    )

    assert isinstance(result, Mapping)
    first = result.to_dict()
    second = result.to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert ESTABLISHED_RETRIEVE_KEYS <= set(first)
    assert result["context_packs"] == first["context_packs"]
    assert retrieval.retrieve_governed(
        case["query"], mode=case["mode"], limit=5, filters=case["filters"]
    ) == first


def test_current_context_brief_performs_exactly_one_base_retrieval(
    synthetic_fixture, monkeypatch
):
    deck, _db = synthetic_fixture
    case = _case(deck, "identifier_lookup_01_kx17")
    from app.core import current_context_brief, retrieval

    original = retrieval.retrieve
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(retrieval, "retrieve", counted)
    brief = current_context_brief.build_current_context_brief(
        case["query"], mode=case["mode"], limit=5
    )

    assert brief["best_evidence"]
    assert calls == 1, "CurrentContextBrief must not initiate a second query retrieval"


def test_supplied_governed_result_prevents_downstream_retrieval(monkeypatch):
    supplied = _governed_stub()
    from app.core import context_object, current_context_brief, retrieval

    def unexpected(*_args, **_kwargs):
        raise AssertionError("a supplied governed result must prevent downstream retrieval")

    monkeypatch.setattr(retrieval, "retrieve", unexpected)
    monkeypatch.setattr(retrieval, "retrieve_governed", unexpected)
    if hasattr(retrieval, "retrieve_governed_result"):
        monkeypatch.setattr(retrieval, "retrieve_governed_result", unexpected)

    context = context_object.assemble(
        "query",
        "shared governed fixture",
        evidence_limit=5,
        question_type="exploratory",
        governed_result=supplied,
    )
    brief = current_context_brief.build_current_context_brief(
        "shared governed fixture",
        limit=5,
        mode="exploration",
        governed_result=supplied,
    )

    assert _pack_ids(context["evidence"]) == [
        ("doc-shared-allowed", "chunk-shared-allowed-0")
    ]
    assert _pack_ids(brief["best_evidence"]) == [
        ("doc-shared-allowed", "chunk-shared-allowed-0")
    ]


def test_answer_surfaces_share_population_withholding_and_citations(monkeypatch):
    _require_operational_mcp_adapter()
    supplied = _governed_stub()
    wire = supplied.to_dict()
    from app.core import context_object, current_context_brief, retrieval
    from tools.boh_mcp_adapter.adapter import BohMcpAdapter

    monkeypatch.setattr(retrieval, "retrieve_governed_result", lambda *_a, **_k: supplied)

    def raw_bypass(*_args, **_kwargs):
        raise AssertionError("answer-oriented consumers must not use raw retrieval")

    monkeypatch.setattr(retrieval, "retrieve", raw_bypass)

    brief = current_context_brief.build_current_context_brief(
        "shared governed fixture",
        limit=5,
        mode="exploration",
        governed_result=supplied,
    )
    context = context_object.assemble(
        "query",
        "shared governed fixture",
        evidence_limit=5,
        question_type="exploratory",
        governed_result=supplied,
    )
    mcp = BohMcpAdapter().retrieve_context("shared governed fixture", limit=5)

    expected_population = _pack_ids(wire["context_packs"])
    assert _pack_ids(brief["best_evidence"]) == expected_population
    assert _pack_ids(context["evidence"]) == expected_population
    assert _pack_ids(mcp["context_packs"]) == expected_population

    expected_citation = "boh://doc-shared-allowed#chunk-shared-allowed-0"
    assert wire["context_packs"][0]["citation_uri"] == expected_citation
    assert brief["best_evidence"][0]["citation_uri"] == expected_citation
    assert context["evidence"][0]["citation_uri"] == expected_citation
    assert mcp["context_packs"][0]["citation_uri"] == expected_citation
    assert wire["context_packs"][0]["source_spans"]
    assert context["evidence"][0]["source_spans"]
    assert mcp["context_packs"][0]["source_spans"]

    required_reason = "policy_withheld_fixture"
    assert required_reason in _withheld_reasons(wire)
    assert required_reason in _withheld_reasons(brief)
    assert required_reason in _withheld_reasons(context)
    assert required_reason in _withheld_reasons(mcp)


def test_established_external_response_keys_are_preserved(synthetic_fixture):
    _require_operational_mcp_adapter()
    deck, _db = synthetic_fixture
    case = _case(deck, "natural_question_01_cedar")
    from app.core import context_object, current_context_brief, retrieval
    from tools.boh_mcp_adapter.adapter import BohMcpAdapter

    retrieve_wire = retrieval.retrieve_governed(
        case["query"], mode=case["mode"], limit=5, filters=case["filters"]
    )
    brief_wire = current_context_brief.build_current_context_brief(
        case["query"], mode=case["mode"], limit=5
    )
    context_wire = context_object.assemble(
        "query", case["query"], evidence_limit=5, question_type="exploratory"
    )
    mcp_wire = BohMcpAdapter().retrieve_context(case["query"], limit=5)

    assert ESTABLISHED_RETRIEVE_KEYS <= set(retrieve_wire)
    assert ESTABLISHED_BRIEF_KEYS <= set(brief_wire)
    assert ESTABLISHED_CONTEXT_KEYS <= set(context_wire)
    assert ESTABLISHED_MCP_KEYS <= set(mcp_wire)


def test_representative_limit_five_sql_counts_meet_rq3_reduction_target(
    synthetic_fixture,
):
    deck, db = synthetic_fixture
    case = _case(deck, "identifier_lookup_01_kx17")
    from app.core import current_context_brief, retrieval

    _retrieve, retrieve_reads = baseline._count_sql_reads(
        db,
        lambda: retrieval.retrieve_governed(
            case["query"], mode=case["mode"], limit=5, filters=case["filters"]
        ),
    )
    _brief, brief_reads = baseline._count_sql_reads(
        db,
        lambda: current_context_brief.build_current_context_brief(
            case["query"], mode=case["mode"], limit=5
        ),
    )

    # Frozen RQ-2 counts for this exact case are 13 (retrieve) and 31 (brief).
    # A >=60% reduction therefore permits at most 5 and 12 statements.
    assert retrieve_reads <= 5 and brief_reads <= 12, (
        "representative limit-5 SQL target missed: "
        f"retrieve={retrieve_reads} (target <= 5), "
        f"brief={brief_reads} (target <= 12)"
    )


def test_retrieval_snapshot_rolls_back_and_closes_on_injected_failure(monkeypatch):
    from app.core import retrieval

    class FakeConnection:
        def __init__(self):
            self.rollbacks = 0
            self.closes = 0

        def execute(self, statement, _params=()):
            assert statement in {"PRAGMA query_only=ON", "BEGIN"}
            return self

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            self.closes += 1

    connection = FakeConnection()
    monkeypatch.setattr(retrieval.db, "get_conn", lambda: connection)
    snapshot = retrieval._RetrievalReadSnapshot()

    with pytest.raises(RuntimeError, match="injected retrieval failure"):
        with snapshot:
            raise RuntimeError("injected retrieval failure")

    assert connection.rollbacks == 1
    assert connection.closes == 1
    assert snapshot.conn is None


def test_batched_metadata_preserves_full_freshness_and_context_conflict_semantics(
    synthetic_fixture,
):
    deck, db = synthetic_fixture
    case = _case(deck, "identifier_lookup_01_kx17")
    target_doc_id = "doc-id-kx17"
    for index in range(11):
        db.execute(
            "INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail) "
            "VALUES (?,?,?,?,?)",
            (target_doc_id, f"missing-related-{index}", "related", 200 + index, "fixture"),
        )
        db.execute(
            "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, acknowledged) "
            "VALUES (?,?,?,?,?,?)",
            ("definition_conflict", f"{target_doc_id},other-{index}", f"term-{index}",
             "synthetic", 200 + index, 0),
        )
    db.execute(
        "INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail) "
        "VALUES (?,?,?,?,?)",
        (target_doc_id, "older-superseding-doc", "superseded_by", 1, "fixture"),
    )

    from app.core import context_object, retrieval

    governed = retrieval.retrieve_governed_result(
        case["query"], mode=case["mode"], limit=5, filters=case["filters"]
    )
    target_pack = next(
        pack for pack in governed.context_packs if pack.get("doc_id") == target_doc_id
    )
    assert len(target_pack["lineage"]) == 10
    assert target_pack["freshness"]["superseded"] is True
    assert target_pack["freshness"]["superseded_by"] == "older-superseding-doc"

    context = context_object.assemble(
        "query",
        case["query"],
        evidence_limit=5,
        question_type="exploratory",
        governed_result=governed,
    )
    assert len(target_pack["conflicts"]) == 10
    assert len(context["conflicts"]) == 11


def test_batched_conflicts_preserve_legacy_like_limit_before_exact_filter(
    synthetic_fixture,
):
    deck, db = synthetic_fixture
    case = _case(deck, "identifier_lookup_01_kx17")
    target_doc_id = "doc-id-kx17"
    for index in range(10):
        db.execute(
            "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, acknowledged) "
            "VALUES (?,?,?,?,?,?)",
            ("definition_conflict", f"{target_doc_id}0{index},other", f"false-{index}",
             "synthetic", 200 + index, 0),
        )
    db.execute(
        "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, acknowledged) "
        "VALUES (?,?,?,?,?,?)",
        ("definition_conflict", f"{target_doc_id},other-exact", "older-exact",
         "synthetic", 1, 0),
    )

    from app.core import context_object, retrieval

    governed = retrieval.retrieve_governed_result(
        case["query"], mode=case["mode"], limit=5, filters=case["filters"]
    )
    target_pack = next(
        pack for pack in governed.context_packs if pack.get("doc_id") == target_doc_id
    )
    assert target_pack["conflicts"] == []
    assert target_pack["why_selected"]["conflict_penalty"] == 0.0

    context = context_object.assemble(
        "query", case["query"], evidence_limit=5, governed_result=governed
    )
    assert "older-exact" in {item.get("term") for item in context["conflicts"]}


def test_batched_audit_context_preserves_repeated_pack_order(synthetic_fixture):
    deck, db = synthetic_fixture
    case = _case(deck, "identifier_lookup_01_kx17")
    from app.core import retrieval

    governed = retrieval.retrieve_governed_result(
        case["query"], mode=case["mode"], limit=5, filters=case["filters"]
    )
    target_pack = next(
        pack for pack in governed.context_packs if pack.get("doc_id") == "doc-id-kx17"
    )
    db.execute(
        "INSERT INTO storage_events (event_id, event_type, card_id, doc_id, detail_json, created_ts) "
        "VALUES (?,?,?,?,?,?)",
        ("rq3-audit-event", "fixture", target_pack["card_id"], target_pack["doc_id"], "{}", 1),
    )
    repeated = [target_pack, target_pack]

    legacy = retrieval._audit_objects(repeated)
    with retrieval._RetrievalReadSnapshot() as snapshot:
        batched = retrieval._audit_objects(repeated, snapshot)

    assert batched == legacy

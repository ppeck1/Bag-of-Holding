import importlib
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.core import planar_gate


@contextmanager
def _client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_RETRIEVAL_TOKEN", "retrieve-token")
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")

    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()

    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db, library


def _auth():
    return {"X-BOH-Retrieval-Token": "retrieve-token"}


def _doc(doc_id: str, title: str, status: str = "draft",
         authority_state: str = "draft", canonical_layer: str = "supporting",
         operator_state: str = "observe") -> str:
    return f"""---
boh:
  id: "{doc_id}"
  document_id: "{doc_id}"
  title: "{title}"
  purpose: "{title}"
  type: "note"
  document_class: "note"
  status: "{status}"
  canonical_layer: "{canonical_layer}"
  authority_state: "{authority_state}"
  review_state: "none"
  project: "Retrieval Gate Test"
  version: "1.0.0"
  updated: "2026-05-26T00:00:00+00:00"
  source_hash: "seed-{doc_id}"
  provenance:
    mode: "test"
    source: "retrieval-gate-test"
  topics: ["retrieval", "gate"]
  scope:
    plane_scope: ["retrieval"]
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: "{operator_state}"
    operator_intent: "capture"
    next_operator: null
---

# {title}

The retrieval target explains bounded context packs for LLM tools.

## Evidence

Hybrid retrieval combines FTS scoring, local lexical semantic similarity, lineage expansion, and authority weighting.
"""


def _index(path, library):
    from app.services.indexer import index_file
    return index_file(path, library)


def test_retrieve_response_contains_gate_result(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        path = library / "gate.md"
        path.write_text(_doc("gate-doc", "Gate Retrieval"), encoding="utf-8")
        _index(path, library)

        res = client.post(
            "/api/retrieve",
            json={"query": "bounded context packs", "mode": "exploration", "limit": 3},
            headers=_auth(),
        )

        assert res.status_code == 200
        payload = res.json()
        assert {"query", "count", "context_packs", "excluded_summary", "audit_context", "retrieval"} <= set(payload)
        assert "planar_context_pack" in payload
        assert "gate_result" in payload
        assert payload["gate_result"]["posture"] in {"answerable", "bounded", "review_required", "blocked"}
        assert "allowed_context_refs" in payload["gate_result"]
        assert "withheld_context_refs" in payload["gate_result"]
        assert payload["gate_result"]["context_pack_id"] == payload["planar_context_pack"]["context_pack_id"]


def test_strict_answer_with_subjective_card_withholds_context(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        from app.core.plane_card import create_llm_output_card

        card = create_llm_output_card(
            topic="Subjective Gate Synthesis",
            text="Subjective gate synthesis for retrieval behavior.",
            actor_id="ollama_local",
            model="llama3.2",
        )

        res = client.post(
            "/api/retrieve",
            json={"query": "Subjective Gate Synthesis", "mode": "strict_answer", "limit": 5},
            headers=_auth(),
        )

        assert res.status_code == 200
        payload = res.json()
        assert payload["context_packs"] == []
        assert any(e["card_id"] == card.id and e["reason"] == "subjective_excluded" for e in payload["excluded_summary"])
        assert card.id in payload["gate_result"]["withheld_context_refs"]


def test_exploration_mode_can_bound_instead_of_blocking_subjective(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        from app.core.plane_card import create_llm_output_card

        card = create_llm_output_card(
            topic="Exploration Gate Synthesis",
            text="Subjective exploration gate synthesis for retrieval behavior.",
            actor_id="ollama_local",
            model="llama3.2",
        )

        res = client.post(
            "/api/retrieve",
            json={"query": "Exploration Gate Synthesis", "mode": "exploration", "limit": 5},
            headers=_auth(),
        )

        assert res.status_code == 200
        payload = res.json()
        assert any(p.get("card_id") == card.id for p in payload["context_packs"])
        assert payload["gate_result"]["posture"] == "bounded"
        assert "subjective_card" in payload["gate_result"]["warning_reasons"]
        assert payload["gate_result"]["blocking_reasons"] == []


def test_gate_blocks_high_risk_source_trust_and_scalar_missing():
    context_pack, gate_result = planar_gate.evaluate_context_pack(
        query="can this source approve canon",
        operation="approve",
        actor={"actor_id": "approver_01", "role": "approver"},
        mode="strict_answer",
        candidate_packs=[
            {
                "card_id": "pc_unknown_source",
                "doc_id": "doc_unknown_source",
                "plane": "informational",
                "payload": {
                    "source_trust": "unknown",
                    "object_status": "imported",
                    "text": "unknown source material",
                },
                "eligibility": {"allowed": True},
            }
        ],
    )

    assert context_pack["context_pack_id"] == gate_result["context_pack_id"]
    assert gate_result["posture"] == "blocked"
    assert "source_trust_unknown_quarantine" in gate_result["blocking_reasons"]
    assert "scalar_basis_missing" in gate_result["blocking_reasons"]
    assert gate_result["l6_proposal_allowed"] is True
    assert "fixture_patch" in gate_result["l6_proposal_types"]
    assert gate_result["withheld_context_refs"] == ["pc_unknown_source"]

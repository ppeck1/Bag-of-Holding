import importlib
from contextlib import contextmanager

from fastapi.testclient import TestClient


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


def _operator_auth():
    return {"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": "local_operator"}


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
  project: "Retrieval Test"
  version: "1.0.0"
  updated: "2026-05-26T00:00:00+00:00"
  source_hash: "seed-{doc_id}"
  provenance:
    mode: "test"
    source: "retrieval-test"
  topics: ["retrieval", "primitive"]
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

| Signal | Purpose |
| --- | --- |
| citation | preserve source span |
| warning | prevent false canon |

See https://example.test/retrieval for connector notes.
"""


def _index(path, library):
    from app.services.indexer import index_file
    return index_file(path, library)


def test_retrieve_requires_separate_retrieval_token_not_operator(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        status = client.get("/api/retrieve/status")
        assert status.status_code == 200
        assert status.json()["header_name"] == "X-BOH-Retrieval-Token"
        assert status.json()["operator_token_required"] is False

        missing = client.post("/api/retrieve", json={"query": "retrieval"})
        assert missing.status_code == 401
        wrong = client.post(
            "/api/retrieve",
            json={"query": "retrieval"},
            headers={"X-BOH-Operator-Token": "operator-token"},
        )
        assert wrong.status_code == 401


def test_index_file_creates_stable_chunks_with_spans_and_types(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (_client_obj, db, library):
        path = library / "retrieval.md"
        path.write_text(_doc("retrieval-doc", "Retrieval Architecture"), encoding="utf-8")
        result = _index(path, library)
        assert result["indexed"] is True

        chunks = db.fetchall("SELECT * FROM doc_chunks WHERE doc_id = ? ORDER BY chunk_index", ("retrieval-doc",))
        assert len(chunks) >= 5
        assert {c["chunk_type"] for c in chunks} >= {"frontmatter", "heading", "body", "table", "link"}
        assert all(c["chunk_id"].startswith("chunk-") for c in chunks)
        assert all(c["byte_end"] >= c["byte_start"] for c in chunks)

        first_ids = [c["chunk_id"] for c in chunks]
        _index(path, library)
        again = db.fetchall("SELECT chunk_id FROM doc_chunks WHERE doc_id = ? ORDER BY chunk_index", ("retrieval-doc",))
        assert [c["chunk_id"] for c in again] == first_ids

        embeddings = db.fetchall(
            "SELECT * FROM doc_chunk_embeddings WHERE chunk_id IN "
            "(SELECT chunk_id FROM doc_chunks WHERE doc_id = ?)",
            ("retrieval-doc",),
        )
        assert len(embeddings) == len(chunks)
        assert {e["embedding_model"] for e in embeddings} == {"boh-local-hash-embedding-v1"}
        assert all(e["dimensions"] == 64 for e in embeddings)


def test_retrieve_returns_ranked_cited_context_pack(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        path = library / "retrieval.md"
        path.write_text(_doc("retrieval-doc", "Retrieval Architecture"), encoding="utf-8")
        _index(path, library)

        res = client.post(
            "/api/retrieve",
            json={"query": "hybrid retrieval authority weighting citations", "mode": "exploration", "limit": 3},
            headers=_auth(),
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["retrieval"]["mode"] == "hybrid_v1"
        assert payload["retrieval"]["read_only"] is True
        assert payload["retrieval"]["embedding_backend"] == "boh-local-hash-embedding-v1"
        assert payload["retrieval"]["context_chars"] <= payload["retrieval"]["max_context_chars"]
        assert payload["count"] >= 1
        pack = payload["context_packs"][0]
        assert pack["doc_id"] == "retrieval-doc"
        assert pack["chunk_id"]
        assert pack["citation"]["chunk_id"] == pack["chunk_id"]
        assert pack["source_span"]["byte_end"] >= pack["source_span"]["byte_start"]
        assert "why_selected" in pack
        assert "embedding_score" in pack["why_selected"]
        assert "provenance" in pack
        assert pack["do_not_treat_as_canonical"] is True


def test_retrieve_filters_and_authority_flag(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        draft = library / "draft.md"
        canon = library / "canon.md"
        draft.write_text(_doc("draft-doc", "Draft Retrieval", status="draft"), encoding="utf-8")
        canon.write_text(
            _doc("canon-doc", "Approved Retrieval", status="draft",
                 authority_state="approved", canonical_layer="supporting"),
            encoding="utf-8",
        )
        _index(draft, library)
        _index(canon, library)

        res = client.get(
            "/api/retrieve",
            params={"q": "bounded context packs", "authority_state": "approved", "limit": 5},
            headers=_auth(),
        )
        assert res.status_code == 200
        packs = res.json()["context_packs"]
        assert packs
        assert {p["doc_id"] for p in packs} == {"canon-doc"}
        assert all(p["do_not_treat_as_canonical"] is False for p in packs)
        assert all(p.get("doc_id") != "draft-doc" for p in packs)
        assert all(p.get("authority_state") == "approved" or p.get("eligibility") for p in packs)


def test_retrieval_card_append_respects_authority_filter(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        draft = library / "draft.md"
        approved = library / "approved.md"
        draft.write_text(_doc("draft-card-doc", "Filter Parity", authority_state="draft"), encoding="utf-8")
        approved.write_text(_doc("approved-card-doc", "Filter Parity", authority_state="approved"), encoding="utf-8")
        _index(draft, library)
        _index(approved, library)

        res = client.post(
            "/api/retrieve",
            json={
                "query": "Filter Parity",
                "mode": "exploration",
                "authority_state": "approved",
                "limit": 10,
            },
            headers=_auth(),
        )
        assert res.status_code == 200
        packs = res.json()["context_packs"]
        assert packs
        assert all(p.get("doc_id") != "draft-card-doc" for p in packs)
        assert {p.get("doc_id") for p in packs if p.get("doc_id")} == {"approved-card-doc"}


def test_retrieval_card_append_respects_status_filter(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        draft = library / "draft.md"
        draft.write_text(_doc("draft-status-doc", "Status Filter Parity", status="draft"), encoding="utf-8")
        _index(draft, library)

        res = client.post(
            "/api/retrieve",
            json={
                "query": "Status Filter Parity",
                "mode": "exploration",
                "status": "canonical",
                "limit": 10,
            },
            headers=_auth(),
        )
        assert res.status_code == 200
        assert res.json()["context_packs"] == []


def test_retrieval_chunk_type_body_does_not_append_plane_cards(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        path = library / "body.md"
        path.write_text(_doc("body-filter-doc", "Body Filter Parity"), encoding="utf-8")
        _index(path, library)

        res = client.post(
            "/api/retrieve",
            json={
                "query": "bounded context packs",
                "mode": "exploration",
                "chunk_type": "body",
                "limit": 10,
            },
            headers=_auth(),
        )
        assert res.status_code == 200
        packs = res.json()["context_packs"]
        assert packs
        assert all(p["chunk_type"] == "body" for p in packs)
        assert all(p.get("card_id") is None or p.get("chunk_id") for p in packs)


def test_card_only_retrieval_respects_metadata_filters(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        created = client.post(
            "/api/planes/cards",
            json={
                "plane": "informational",
                "topic": "Card Only Parity",
                "d": 0,
                "m": "contain",
                "payload": {
                    "text": "Card only parity result",
                    "status": "draft",
                    "authority_state": "draft",
                    "canonical_layer": "supporting",
                    "project": "Retrieval Test",
                    "quality": 0.6,
                    "confidence": 0.6,
                    "state": "active",
                },
            },
            headers=_operator_auth(),
        )
        assert created.status_code == 200

        blocked = client.post(
            "/api/retrieve",
            json={
                "query": "Card Only Parity",
                "mode": "exploration",
                "authority_state": "approved",
                "limit": 5,
            },
            headers=_auth(),
        )
        assert blocked.status_code == 200
        assert blocked.json()["context_packs"] == []

        allowed = client.post(
            "/api/retrieve",
            json={
                "query": "Card Only Parity",
                "mode": "exploration",
                "authority_state": "draft",
                "limit": 5,
            },
            headers=_auth(),
        )
        assert allowed.status_code == 200
        assert any(p["chunk_type"] == "plane_card" for p in allowed.json()["context_packs"])


def test_retrieve_includes_lineage_and_conflict_warnings(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        a = library / "a.md"
        b = library / "b.md"
        a.write_text(_doc("a-doc", "Alpha Retrieval"), encoding="utf-8")
        b.write_text(_doc("b-doc", "Beta Retrieval"), encoding="utf-8")
        _index(a, library)
        _index(b, library)
        db.execute(
            "INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail) VALUES (?,?,?,?,?)",
            ("a-doc", "b-doc", "derived_from", 1, "test lineage"),
        )
        db.execute(
            "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, acknowledged) VALUES (?,?,?,?,?,?)",
            ("definition_conflict", "a-doc,b-doc", "retrieval", "retrieval", 1, 0),
        )

        res = client.post(
            "/api/retrieve",
            json={"query": "Alpha retrieval bounded context", "mode": "exploration", "limit": 2},
            headers=_auth(),
        )
        assert res.status_code == 200
        pack = next(p for p in res.json()["context_packs"] if p["doc_id"] == "a-doc")
        assert pack["lineage"]
        assert pack["conflicts"]
        assert "open_conflicts_present" in pack["warnings"]

        expanded = client.post(
            "/api/retrieve",
            json={"query": "Alpha bounded context", "mode": "exploration", "limit": 5, "include_lineage": True},
            headers=_auth(),
        )
        assert expanded.status_code == 200
        expanded_packs = expanded.json()["context_packs"]
        assert any(
            p["doc_id"] == "b-doc"
            and str(p["why_selected"]["retrieval_source"]).startswith("lineage_expansion")
            for p in expanded_packs
        )


def test_retrieval_golden_question_expected_source_doc(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        retrieval_doc = library / "retrieval.md"
        unrelated_doc = library / "garden.md"
        retrieval_doc.write_text(_doc("retrieval-doc", "Retrieval Architecture"), encoding="utf-8")
        unrelated_doc.write_text(
            _doc("garden-doc", "Garden Notes").replace(
                "The retrieval target explains bounded context packs for LLM tools.",
                "The garden target explains seed trays and seasonal planting notes.",
            ).replace(
                "Hybrid retrieval combines FTS scoring, local lexical semantic similarity, lineage expansion, and authority weighting.",
                "Seed trays need labels, watering cadence, and a cold frame plan.",
            ),
            encoding="utf-8",
        )
        _index(retrieval_doc, library)
        _index(unrelated_doc, library)

        golden_questions = [
            {
                "query": "How does BOH build cited context packs for LLM tools?",
                "expected_doc_id": "retrieval-doc",
                "expected_chunk_terms": {"context", "packs"},
            }
        ]
        for case in golden_questions:
            res = client.post(
                "/api/retrieve",
                json={"query": case["query"], "mode": "exploration", "limit": 3},
                headers=_auth(),
            )
            assert res.status_code == 200
            packs = res.json()["context_packs"]
            assert packs
            assert packs[0]["doc_id"] == case["expected_doc_id"]
            top_text = (packs[0]["snippet"] + " " + packs[0]["heading_path"]).lower()
            assert case["expected_chunk_terms"] <= set(top_text.split()) | set(top_text.replace(".", "").split())


def test_retrieval_modes_exclude_or_include_subjective_cards(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, _library):
        from app.core.plane_card import create_llm_output_card

        card = create_llm_output_card(
            topic="Subjective Retrieval Synthesis",
            text="Subjective synthesis about prism retrieval mode behavior.",
            actor_id="ollama_local",
            model="llama3.2",
        )

        strict = client.post(
            "/api/retrieve",
            json={"query": "prism retrieval mode behavior", "mode": "strict_answer", "limit": 5},
            headers=_auth(),
        )
        assert strict.status_code == 200
        assert all(p.get("card_id") != card.id for p in strict.json()["context_packs"])
        assert any(e["card_id"] == card.id and e["reason"] == "subjective_excluded"
                   for e in strict.json()["excluded_summary"])

        explore = client.post(
            "/api/retrieve",
            json={"query": "prism retrieval mode behavior", "mode": "exploration", "limit": 5},
            headers=_auth(),
        )
        assert explore.status_code == 200
        packs = explore.json()["context_packs"]
        assert any(p.get("card_id") == card.id for p in packs)
        subjective = next(p for p in packs if p.get("card_id") == card.id)
        assert subjective["plane"] == "subjective"
        assert "subjective_card" in subjective["warnings"]
        assert subjective["eligibility"]["allowed"] is True

        events = db.fetchall("SELECT * FROM storage_events WHERE event_type = 'retrieval_performed'")
        assert len(events) >= 2


def test_strict_mode_filtered_context_reports_zero_chars(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        path = library / "draft.md"
        path.write_text(_doc("strict-draft-doc", "Strict Draft"), encoding="utf-8")
        _index(path, library)

        res = client.post(
            "/api/retrieve",
            json={"query": "bounded context packs", "mode": "strict_answer", "limit": 5},
            headers=_auth(),
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["count"] == 0
        assert payload["context_packs"] == []
        assert payload["retrieval"]["context_chars"] == 0


def test_audit_mode_returns_trace_context(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        path = library / "audit.md"
        path.write_text(_doc("audit-doc", "Audit Retrieval"), encoding="utf-8")
        _index(path, library)

        res = client.post(
            "/api/retrieve",
            json={"query": "Audit retrieval context packs", "mode": "audit_provenance", "limit": 5},
            headers=_auth(),
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["retrieval"]["planar_mode"] == "audit_provenance"
        assert "storage_events" in payload["audit_context"]
        assert payload["audit_context"]["storage_events"]


def test_unknown_retrieval_mode_rejected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.post(
            "/api/retrieve",
            json={"query": "anything", "mode": "made_up"},
            headers=_auth(),
        )
        assert res.status_code == 422

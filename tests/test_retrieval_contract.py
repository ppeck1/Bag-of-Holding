"""Contract tests for additive external-consumer retrieval fields (v0.1).

Covers citation_uri, source_spans, top-level warnings rollup, the plane_card
null-case, and that no pre-existing response key changed name/type.
"""

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
"""


def _index(path, library):
    from app.services.indexer import index_file
    return index_file(path, library)


def test_document_pack_has_citation_uri_and_source_spans(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        path = library / "retrieval.md"
        path.write_text(_doc("retrieval-doc", "Retrieval Architecture"), encoding="utf-8")
        _index(path, library)

        res = client.post(
            "/api/retrieve",
            json={"query": "hybrid retrieval bounded context packs", "mode": "exploration", "limit": 3},
            headers=_auth(),
        )
        assert res.status_code == 200
        payload = res.json()
        pack = next(p for p in payload["context_packs"] if p.get("chunk_id"))

        assert pack["citation_uri"] == f"boh://{pack['doc_id']}#{pack['chunk_id']}"
        assert pack["source_spans"] == [pack["source_span"]]
        assert isinstance(pack["source_spans"], list)
        assert len(pack["source_spans"]) == 1


def test_top_level_warnings_is_deduped_string_list(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        a = library / "a.md"
        b = library / "b.md"
        a.write_text(_doc("a-doc", "Alpha Retrieval"), encoding="utf-8")
        b.write_text(_doc("b-doc", "Beta Retrieval"), encoding="utf-8")
        _index(a, library)
        _index(b, library)
        db.execute(
            "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, acknowledged) VALUES (?,?,?,?,?,?)",
            ("definition_conflict", "a-doc,b-doc", "retrieval", "retrieval", 1, 0),
        )

        res = client.post(
            "/api/retrieve",
            json={"query": "Alpha retrieval bounded context", "mode": "exploration", "limit": 3},
            headers=_auth(),
        )
        assert res.status_code == 200
        warnings = res.json()["warnings"]
        assert isinstance(warnings, list)
        assert all(isinstance(w, str) for w in warnings)
        assert len(warnings) == len(set(warnings))
        assert "do_not_treat_as_canonical" in warnings


def test_plane_card_pack_has_null_citation_uri_and_empty_spans(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        created = client.post(
            "/api/planes/cards",
            json={
                "plane": "informational",
                "topic": "Card Null Case Parity",
                "d": 0,
                "m": "contain",
                "payload": {
                    "text": "Card null case parity result for contract test",
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

        res = client.post(
            "/api/retrieve",
            json={"query": "Card Null Case Parity", "mode": "exploration", "limit": 5},
            headers=_auth(),
        )
        assert res.status_code == 200
        packs = res.json()["context_packs"]
        card_pack = next(p for p in packs if p.get("chunk_type") == "plane_card")
        assert card_pack["chunk_id"] is None
        assert card_pack["source_span"] is None
        assert card_pack["citation_uri"] is None
        assert card_pack["source_spans"] == []


def test_legacy_response_keys_unchanged(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        path = library / "retrieval.md"
        path.write_text(_doc("retrieval-doc", "Retrieval Architecture"), encoding="utf-8")
        _index(path, library)

        res = client.post(
            "/api/retrieve",
            json={"query": "hybrid retrieval bounded context packs", "mode": "exploration", "limit": 3},
            headers=_auth(),
        )
        assert res.status_code == 200
        payload = res.json()

        # Top-level legacy keys, with prior types.
        assert isinstance(payload["query"], str)
        assert isinstance(payload["count"], int)
        assert isinstance(payload["context_packs"], list)
        assert isinstance(payload["excluded_summary"], list)
        assert isinstance(payload["audit_context"], dict)
        assert isinstance(payload["retrieval"], dict)
        assert isinstance(payload["gate_result"], dict)

        pack = next(p for p in payload["context_packs"] if p.get("chunk_id"))
        # citation stays a dict; source_span stays a single dict.
        assert isinstance(pack["citation"], dict)
        assert pack["citation"]["chunk_id"] == pack["chunk_id"]
        assert isinstance(pack["source_span"], dict)
        assert isinstance(pack["warnings"], list)


# --- boh_retrieval_fts_query_hyphen_hardening_v0_1 ---


HYPHEN_DOC = """---
boh:
  id: "hyphen-doc"
  title: "Hyphen Hardening Target"
  status: "draft"
  authority_state: "draft"
---

# Hyphen Hardening Target

The alpha-beta pipeline uses quux-mode settings for the gamma:delta channel here.
"""


def test_operator_bearing_queries_do_not_error(tmp_path, monkeypatch):
    """FTS5 operator characters in user queries ('-', ':', parens) must never 500
    /api/retrieve nor degrade /api/search into an error payload."""
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        path = library / "hyphen.md"
        path.write_text(HYPHEN_DOC, encoding="utf-8")
        _index(path, library)

        for q in ("alpha-beta pipeline", "quux-mode", "gamma:delta channel",
                  "alpha-beta (settings)"):
            res = client.post("/api/retrieve",
                              json={"query": q, "mode": "exploration", "limit": 5},
                              headers=_auth())
            assert res.status_code == 200, (q, res.text)
        hit = client.post("/api/retrieve",
                          json={"query": "alpha-beta pipeline quux-mode",
                                "mode": "exploration", "limit": 5}, headers=_auth())
        assert "hyphen-doc" in {p.get("doc_id") for p in hit.json()["context_packs"]}

        from app.core.search import search as search_core
        rows = search_core("alpha-beta quux-mode", limit=10)
        assert rows and not any("error" in r for r in rows)
        assert any("hyphen" in str(r.get("path", "")) for r in rows)
        # Pure-operator garbage degrades to empty, never an exception/error payload.
        assert search_core("---:::((()))", limit=5) == []


# --- WO-R1 (`boh_retrieval_provenance_completion_v0_1`) additive blocks ---


def _retrieve_first_doc_pack(client, query="hybrid retrieval bounded context packs"):
    res = client.post(
        "/api/retrieve",
        json={"query": query, "mode": "exploration", "limit": 3},
        headers=_auth(),
    )
    assert res.status_code == 200
    return next(p for p in res.json()["context_packs"] if p.get("chunk_id"))


def test_pack_has_review_state_and_freshness_blocks(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        path = library / "retrieval.md"
        path.write_text(_doc("retrieval-doc", "Retrieval Architecture"), encoding="utf-8")
        _index(path, library)

        pack = _retrieve_first_doc_pack(client)

        review = pack["review_state"]
        assert review["last_review"] is None
        assert review["review_count"] == 0

        fresh = pack["freshness"]
        assert set(fresh) == {"age_days", "source", "valid_until", "superseded", "superseded_by"}
        # Fold-resolver column priority: epistemic_last_evaluated then updated_ts.
        assert fresh["source"] in ("epistemic_last_evaluated", "updated_ts", None)
        if fresh["source"] is not None:
            assert isinstance(fresh["age_days"], int)
            assert fresh["age_days"] >= 0
        assert fresh["superseded"] is False
        assert fresh["superseded_by"] is None


def test_review_state_reflects_latest_provenance_artifact(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        path = library / "retrieval.md"
        path.write_text(_doc("retrieval-doc", "Retrieval Architecture"), encoding="utf-8")
        _index(path, library)
        for artifact_id, action, approved_at in (
            ("art-1", "review_artifact", 100),
            ("art-2", "canonical_promotion", 200),
        ):
            db.execute(
                "INSERT INTO provenance_artifacts (artifact_id, approval_id, action_type, "
                "document_id, from_state, to_state, approved_by, approved_at, reason, "
                "signature, artifact_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (artifact_id, f"appr-{artifact_id}", action, "retrieval-doc",
                 "draft", "approved", "test_operator", approved_at, "contract test",
                 "sig", "{}"),
            )

        pack = _retrieve_first_doc_pack(client)
        review = pack["review_state"]
        assert review["review_count"] == 2
        assert review["last_review"]["action_type"] == "canonical_promotion"
        assert review["last_review"]["approved_by"] == "test_operator"
        assert review["last_review"]["approved_at"] == 200
        assert review["last_review"]["from_state"] == "draft"
        assert review["last_review"]["to_state"] == "approved"


def test_conflict_entries_carry_resolution_status(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        path = library / "retrieval.md"
        path.write_text(_doc("retrieval-doc", "Retrieval Architecture"), encoding="utf-8")
        _index(path, library)
        db.execute(
            "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, acknowledged) VALUES (?,?,?,?,?,?)",
            ("definition_conflict", "retrieval-doc,other-doc", "retrieval", "retrieval", 1, 0),
        )

        pack = _retrieve_first_doc_pack(client)
        assert pack["conflicts"]
        assert all(c["resolution_status"] == "open" for c in pack["conflicts"])

        db.execute("UPDATE conflicts SET acknowledged = 1")
        pack = _retrieve_first_doc_pack(client)
        assert pack["conflicts"]
        assert all(c["resolution_status"] == "acknowledged" for c in pack["conflicts"])


def test_freshness_supersession_pointer(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        path = library / "retrieval.md"
        path.write_text(_doc("retrieval-doc", "Retrieval Architecture"), encoding="utf-8")
        _index(path, library)
        db.execute(
            "INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts) VALUES (?,?,?,?)",
            ("retrieval-doc", "newer-doc", "superseded_by", 1),
        )

        pack = _retrieve_first_doc_pack(client)
        assert pack["freshness"]["superseded"] is True
        assert pack["freshness"]["superseded_by"] == "newer-doc"


def test_card_pack_review_state_and_freshness_are_null(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        created = client.post(
            "/api/planes/cards",
            json={
                "plane": "informational",
                "topic": "Card Null Case Parity",
                "d": 0,
                "m": "contain",
                "payload": {
                    "text": "Card null case parity result for contract test",
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

        res = client.post(
            "/api/retrieve",
            json={"query": "Card Null Case Parity", "mode": "exploration", "limit": 5},
            headers=_auth(),
        )
        assert res.status_code == 200
        card_pack = next(p for p in res.json()["context_packs"] if p.get("chunk_type") == "plane_card")
        assert card_pack["review_state"] is None
        assert card_pack["freshness"] is None

from __future__ import annotations

import importlib
from contextlib import contextmanager

from fastapi.testclient import TestClient


DOC = """---
boh:
  id: "brief-doc"
  document_id: "brief-doc"
  title: "Current Context Brief Fixture"
  purpose: "Current Context Brief Fixture"
  type: "note"
  document_class: "note"
  status: "draft"
  canonical_layer: "supporting"
  authority_state: "draft"
  review_state: "none"
  project: "Brief Test"
  version: "1.0.0"
  updated: "2026-07-08T00:00:00+00:00"
  source_hash: "seed-brief-doc"
  provenance:
    mode: "test"
    source: "current-context-brief-test"
  topics: ["context", "brief", "retrieval"]
  scope:
    plane_scope: ["retrieval"]
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: "observe"
    operator_intent: "capture"
    next_operator: null
---

# Current Context Brief Fixture

The current context brief fixture explains newest evidence, best evidence,
unknowns, warnings, provenance, and bounded LLM instructions.
"""


@contextmanager
def _client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_RETRIEVAL_TOKEN", "retrieve-token")
    monkeypatch.delenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", raising=False)

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


def _seed(library):
    from app.services.indexer import index_file

    path = library / "brief.md"
    path.write_text(DOC, encoding="utf-8")
    index_file(path, library)


def test_current_context_brief_requires_retrieval_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        assert client.get(
            "/api/current-context-brief",
            params={"topic": "current context brief"},
        ).status_code == 401
        bad = client.post(
            "/api/current-context-brief",
            json={"topic": "current context brief"},
            headers={"X-BOH-Retrieval-Token": "wrong"},
        )
        assert bad.status_code == 403


def test_current_context_brief_contract_shape(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        _seed(library)

        response = client.post(
            "/api/current-context-brief",
            json={"topic": "newest evidence best evidence bounded instructions", "limit": 5},
            headers=_auth(),
        )

        assert response.status_code == 200
        brief = response.json()
        assert brief["contract"] == "CurrentContextBrief v0.1"
        assert brief["topic"] == "newest evidence best evidence bounded instructions"
        assert brief["answerable_now"] is True
        assert brief["current_context_summary"]
        assert brief["newest_evidence"]
        assert brief["best_evidence"]
        assert brief["best_evidence"][0]["doc_id"] == "brief-doc"
        assert brief["best_evidence"][0]["citation_uri"].startswith("boh://brief-doc#")
        assert "provenance" in brief["best_evidence"][0]
        assert "unknowns" in brief
        assert "warnings" in brief
        assert brief["llm_instructions"]["treat_as"] == "bounded_context"
        assert "canon status" in brief["llm_instructions"]["do_not_infer"]


def test_current_context_brief_surfaces_conflicts_and_withheld(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        _seed(library)
        db.execute(
            "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, "
            "acknowledged) VALUES (?,?,?,?,?,?)",
            ("definition_conflict", "brief-doc,other-doc", "brief", "retrieval", 1, 0),
        )

        response = client.get(
            "/api/current-context-brief",
            params={"topic": "current context brief fixture", "mode": "exploration"},
            headers=_auth(),
        )

        assert response.status_code == 200
        brief = response.json()
        assert brief["superseded_or_conflicted"]
        assert any(item.get("term") == "brief" for item in brief["superseded_or_conflicted"])
        assert isinstance(brief["withheld"], list)

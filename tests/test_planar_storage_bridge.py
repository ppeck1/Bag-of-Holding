import hashlib
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
    return {"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": "local_operator"}


def _doc(doc_id="bridge-doc", title="Bridge Source"):
    return f"""---
boh:
  id: "{doc_id}"
  document_id: "{doc_id}"
  title: "{title}"
  purpose: "{title}"
  type: "note"
  document_class: "note"
  status: "draft"
  canonical_layer: "supporting"
  authority_state: "draft"
  review_state: "none"
  project: "Planar Bridge"
  version: "1.0.0"
  updated: "2026-05-26T00:00:00+00:00"
  source_hash: "seed-{doc_id}"
  provenance:
    mode: "test"
  topics: ["bridge"]
  scope:
    plane_scope: ["bridge"]
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: "observe"
    operator_intent: "capture"
---

# {title}

This source should be wrapped without mutating the original file.
"""


def _index(path, library):
    from app.services.indexer import index_file
    return index_file(path, library)


def test_plane_registry_and_compatibility_view_exist(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, _library):
        res = client.get("/api/planes/registry")
        assert res.status_code == 200
        plane_ids = {p["plane_id"] for p in res.json()["planes"]}
        assert {"informational", "subjective", "canonical"} <= plane_ids

        view_rows = db.fetchall("SELECT * FROM plane_cards")
        assert view_rows == []


def test_invalid_plane_card_inputs_rejected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        bad_plane = client.post(
            "/api/planes/cards",
            json={"plane": "made_up", "topic": "bad", "d": 0, "m": "contain"},
            headers=_auth(),
        )
        assert bad_plane.status_code == 422

        bad_d = client.post(
            "/api/planes/cards",
            json={"plane": "informational", "topic": "bad", "d": 2, "m": "contain"},
            headers=_auth(),
        )
        assert bad_d.status_code == 422

        bad_m = client.post(
            "/api/planes/cards",
            json={"plane": "informational", "topic": "bad", "d": 0, "m": "collapse"},
            headers=_auth(),
        )
        assert bad_m.status_code == 422

        bad_qc = client.post(
            "/api/planes/cards",
            json={
                "plane": "informational",
                "topic": "bad",
                "d": 0,
                "m": "contain",
                "payload": {"quality": 1.4, "confidence": 0.5},
            },
            headers=_auth(),
        )
        assert bad_qc.status_code == 422


def test_source_wrap_preserves_file_and_writes_trace_events(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        path = library / "bridge.md"
        path.write_text(_doc(), encoding="utf-8")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = _index(path, library)
        assert result["indexed"] is True

        res = client.post("/api/planes/wrap/bridge-doc", headers=_auth())
        assert res.status_code == 200
        payload = res.json()
        assert payload["source_preserved"] is True
        card = payload["card"]
        assert card["plane"] == "informational"
        assert card["card_type"] == "source_document"
        assert card["d"] == 0
        assert card["m"] == "contain"
        assert card["payload"]["quality"] == 0.5
        assert card["payload"]["confidence"] == 0.5
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before

        events = db.fetchall("SELECT event_type FROM storage_events WHERE doc_id = ?", ("bridge-doc",))
        event_types = {e["event_type"] for e in events}
        assert "plane_card_wrapped" in event_types or "plane_card_updated" in event_types


def test_backfill_is_idempotent_and_trace_visible(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        for name in ("a", "b"):
            p = library / f"{name}.md"
            p.write_text(_doc(f"{name}-doc", f"{name} Source"), encoding="utf-8")
            _index(p, library)

        first = client.post("/api/planes/backfill", headers=_auth())
        second = client.post("/api/planes/backfill", headers=_auth())
        assert first.status_code == 200
        assert second.status_code == 200
        cards = db.fetchall("SELECT doc_id FROM cards ORDER BY doc_id")
        assert [c["doc_id"] for c in cards] == ["a-doc", "b-doc"]

        events = client.get("/api/planes/storage-events?limit=20")
        assert events.status_code == 200
        assert events.json()["count"] >= 2


def test_llm_output_stored_as_subjective_non_authoritative_card(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, _library):
        res = client.post(
            "/api/planes/llm-output",
            json={
                "topic": "Candidate field",
                "text": "A possible synthesis, not canon.",
                "actor_id": "ollama_local",
                "model": "llama3.2",
            },
            headers=_auth(),
        )
        assert res.status_code == 200
        card = res.json()["card"]
        assert card["plane"] == "subjective"
        assert card["card_type"] == "llm_synthesis"
        assert card["d"] == 0
        assert card["m"] == "contain"
        assert card["payload"]["non_authoritative"] is True
        assert card["authority"]["llm_may_approve"] is False
        assert card["authority"]["may_promote"] == ["human_owner"]

        events = db.fetchall("SELECT * FROM storage_events WHERE card_id = ?", (card["id"],))
        assert [e["event_type"] for e in events] == ["llm_output_recorded"]

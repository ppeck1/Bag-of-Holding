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

    import app.core.auth as auth
    import app.api.main as main
    importlib.reload(auth)
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db, library


def _auth():
    return {"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": "local_operator"}


def test_folded_node_packet_is_read_only_and_has_expected_facets(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, _library):
        demo = client.post("/api/input/demo-seed", headers=_auth())
        assert demo.status_code == 200
        anchor = demo.json()["folded_node_demo"]["anchor_doc_id"]

        card_count_before = db.fetchone("SELECT COUNT(*) AS n FROM cards")["n"]
        event_count_before = db.fetchone("SELECT COUNT(*) AS n FROM storage_events")["n"]

        res = client.get(f"/api/docs/{anchor}/fold")
        assert res.status_code == 200
        packet = res.json()

        assert packet["doc_id"] == anchor
        assert set(packet["facets"]) == {
            "source",
            "lifecycle",
            "authority",
            "provenance",
            "conflicts",
            "chunks",
            "plane_card",
            "planar_gate",
            "audit",
        }
        assert packet["facets"]["plane_card"]["present"] is True
        assert packet["facets"]["conflicts"]["count"] >= 1
        assert packet["facets"]["chunks"]["count"] >= 1
        assert packet["facets"]["provenance"]["lineage"]
        assert packet["facets"]["planar_gate"]["gate_result"]["posture"] in {
            "answerable",
            "bounded",
            "review_required",
            "blocked",
        }
        assert packet["facets"]["audit"]["audit_log"]

        assert db.fetchone("SELECT COUNT(*) AS n FROM cards")["n"] == card_count_before
        assert db.fetchone("SELECT COUNT(*) AS n FROM storage_events")["n"] == event_count_before


def test_folded_node_ui_static_wiring():
    index_html = open("app/ui/index.html", encoding="utf-8").read()
    app_js = open("app/ui/app.js", encoding="utf-8").read()

    assert 'id="reader-fold"' in index_html
    assert "/fold" in app_js
    assert "renderFoldedNodePacket" in app_js
    assert "Source" in app_js
    assert "Planar Gate" in app_js

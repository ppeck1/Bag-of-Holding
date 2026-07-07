"""WO-1.1 closure addendum — v2 Library "PlaneCards" tab correction.

The v2 Library `cards` tab previously called the plane-SUMMARY endpoint (`/api/planes`) and rendered
non-existent fields (`card_id`/`type`/`source_doc_id`). It must call the PlaneCard list endpoint
(`/api/planes/cards`) and render the real fields (`id`/`plane`/`card_type`/`topic`/`b`/`d`/`m`/
`valid_until`/`doc_id`), with a truthful empty state. `/api/planes` must remain the plane summary.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

LIBRARY_JS = Path(__file__).parent.parent / "app" / "ui2" / "js" / "screens" / "library.js"


def _src() -> str:
    return LIBRARY_JS.read_text(encoding="utf-8")


class TestLibraryPlaneCardsSource:
    def test_calls_planecards_endpoint_not_plane_summary(self):
        src = _src()
        assert "/api/planes/cards?limit=200" in src
        assert "libraryParam(activeLibraryId)" in src
        # the cards tab must NOT fetch the plane-summary endpoint
        assert 'api("/api/planes?limit=200")' not in src

    def test_renders_actual_planecard_fields(self):
        src = _src()
        for field in ("c.id", "c.plane", "c.card_type", "c.topic", "c.b", "c.d", "c.m",
                      "c.valid_until", "c.doc_id"):
            assert field in src, f"missing PlaneCard field render: {field}"
        # reads the PlaneCard list response key
        assert "d.cards" in src

    def test_does_not_use_wrong_field_names(self):
        src = _src()
        for wrong in ("card_id", "source_doc_id", "p.type"):
            assert wrong not in src, f"stale wrong field still referenced: {wrong}"

    def test_tab_label_and_subtitle_say_planecards(self):
        src = _src()
        assert 'label: "PlaneCards"' in src and 'label: "Domain Cards"' not in src
        assert "inspect PlaneCards." in src and "inspect domain cards." not in src

    def test_truthful_empty_state(self):
        src = _src()
        assert '"No PlaneCards yet"' in src
        assert "operator-gated backfill" in src
        assert '"No domain cards yet"' not in src

    def test_no_domains_tab_added(self):
        # the separate Domains subject-taxonomy axis stays diagnostic-only (no doc->domain linkage)
        assert 'label: "Domains"' not in _src()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    library = tmp_path / "library"; library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    import app.db.connection as db_conn
    db_conn.DB_PATH = str(db_path)
    db_conn.init_db()
    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as c:
        yield c


def test_planes_summary_and_cards_endpoints_are_distinct(client):
    summary = client.get("/api/planes?limit=200")
    assert summary.status_code == 200
    body = summary.json()
    assert "planes" in body and "cards" not in body   # plane summary, NOT a card list

    cards = client.get("/api/planes/cards?limit=200")
    assert cards.status_code == 200
    assert "cards" in cards.json()                     # the actual PlaneCard list endpoint

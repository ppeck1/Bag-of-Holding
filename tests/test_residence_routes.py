"""Phase 7 Residence Map surface tests (TASK 3.3).

Verifies the read-only /api/residence/map route:
- inspectable: a recorded residence row appears with its fields
- filterable: status filter + limit clamping
- single-record lookup: 200 for a known original_ref, 404 for unknown
- read-only / no canon grant: GET handlers perform no DB writes and never
  expose canon_eligible=True
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def residence_client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
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

    from app.core import correction_ledger

    with TestClient(main.app) as client:
        yield client, db_conn, correction_ledger


def _record(ledger, *, original, current=None, location="PlaneCard", status="active",
            reason="moved", locator="library/x.md"):
    return ledger.upsert_information_residence(
        original_ref=original,
        current_ref=current or f"{original}-v2",
        current_location=location,
        status=status,
        reason=reason,
        human_readable_locator=locator,
    )


# ---------------------------------------------------------------------------
# Acceptance #1 -- inspectable
# ---------------------------------------------------------------------------

def test_empty_map_returns_200_empty_list(residence_client):
    client, _, _ = residence_client
    resp = client.get("/api/residence/map")
    assert resp.status_code == 200
    assert resp.json() == {"residences": []}


def test_recorded_residence_is_inspectable(residence_client):
    client, _, ledger = residence_client
    _record(ledger, original="ref-a", current="ref-a-v2", location="SourceVersion",
            status="superseded", reason="corrected", locator="library/a.md")
    rows = client.get("/api/residence/map").json()["residences"]
    assert len(rows) == 1
    row = rows[0]
    assert row["original_ref"] == "ref-a"
    assert row["current_ref"] == "ref-a-v2"
    assert row["current_location"] == "SourceVersion"
    assert row["status"] == "superseded"
    assert row["human_readable_locator"] == "library/a.md"
    assert row["reason"] == "corrected"
    assert not any(k.endswith("_json") for k in row)


# ---------------------------------------------------------------------------
# Acceptance #2 -- filterable
# ---------------------------------------------------------------------------

def test_status_filter_returns_only_matching(residence_client):
    client, _, ledger = residence_client
    _record(ledger, original="a", status="active")
    _record(ledger, original="b", status="superseded")
    rows = client.get("/api/residence/map", params={"status": "superseded"}).json()["residences"]
    assert [r["status"] for r in rows] == ["superseded"]


def test_limit_is_clamped_and_bounds_count(residence_client):
    client, _, ledger = residence_client
    for i in range(5):
        _record(ledger, original=f"r{i}")
    assert client.get("/api/residence/map", params={"limit": 99999}).status_code == 200
    assert len(client.get("/api/residence/map", params={"limit": 2}).json()["residences"]) == 2


# ---------------------------------------------------------------------------
# Acceptance #3 -- single-record lookup (keyed by original_ref)
# ---------------------------------------------------------------------------

def test_single_record_found(residence_client):
    client, _, ledger = residence_client
    _record(ledger, original="ref-a")
    resp = client.get("/api/residence/map/ref-a")
    assert resp.status_code == 200
    assert resp.json()["original_ref"] == "ref-a"


def test_single_record_unknown_is_404(residence_client):
    client, _, _ = residence_client
    assert client.get("/api/residence/map/nope").status_code == 404


# ---------------------------------------------------------------------------
# Acceptance #4 -- read-only / no canon grant
# ---------------------------------------------------------------------------

def test_get_performs_no_db_writes(residence_client, monkeypatch):
    client, db_conn, ledger = residence_client
    _record(ledger, original="ref-a")

    def _boom(*a, **k):
        raise AssertionError("residence map route must not execute writes")

    monkeypatch.setattr(db_conn, "execute", _boom, raising=False)
    monkeypatch.setattr(db_conn, "executemany", _boom, raising=False)
    resp = client.get("/api/residence/map")
    assert resp.status_code == 200
    assert len(resp.json()["residences"]) == 1


def test_canon_eligible_never_exposed_true(residence_client):
    client, _, ledger = residence_client
    ledger.upsert_information_residence(
        original_ref="ref-z", current_ref="ref-z-v2", current_location="PlaneCard",
        status="active", reason="r", human_readable_locator="library/z.md",
        detail={"canon_eligible": True},
    )
    rows = client.get("/api/residence/map").json()["residences"]
    assert rows

    def _assert_no_true(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "canon_eligible":
                    assert v is False
                _assert_no_true(v)
        elif isinstance(node, list):
            for v in node:
                _assert_no_true(v)

    for row in rows:
        _assert_no_true(row)
    _assert_no_true(client.get("/api/residence/map/ref-z").json())

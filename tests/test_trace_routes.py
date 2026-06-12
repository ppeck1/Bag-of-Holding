"""Phase 7 Trace Ledger surface tests (TASK 3.1).

Verifies the read-only /api/trace/gate-results route:
- inspectable: a recorded gate result appears in the list with its fields
- filterable: posture filter + limit clamping
- single-record lookup: 200 for a known id, 404 for unknown
- read-only / no canon grant: GET handlers perform no DB writes and never
  expose canon_eligible=True
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def trace_client(tmp_path, monkeypatch):
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


def _record(ledger, *, ref, posture, blocking=None, warning=None, allowed=None, withheld=None):
    return ledger.record_gate_result(
        {"context_pack_id": f"ctx-{ref}", "query": "q", "operation": "answer_context",
         "actor_id": "reader", "mode": "exploration"},
        {"posture": posture,
         "blocking_reasons": blocking or [],
         "warning_reasons": warning or [],
         "allowed_context_refs": allowed or [],
         "withheld_context_refs": withheld or []},
    )


# ---------------------------------------------------------------------------
# Acceptance #1 -- inspectable
# ---------------------------------------------------------------------------

def test_empty_ledger_returns_200_empty_list(trace_client):
    client, _, _ = trace_client
    resp = client.get("/api/trace/gate-results")
    assert resp.status_code == 200
    assert resp.json() == {"gate_results": []}


def test_recorded_gate_result_is_inspectable(trace_client):
    client, _, ledger = trace_client
    _record(ledger, ref="a", posture="blocked",
            blocking=["actor_role_operation_denied"], withheld=["x"])
    resp = client.get("/api/trace/gate-results")
    assert resp.status_code == 200
    rows = resp.json()["gate_results"]
    assert len(rows) == 1
    row = rows[0]
    assert row["posture"] == "blocked"
    assert row["blocking_reasons"] == ["actor_role_operation_denied"]
    assert row["withheld_context_refs"] == ["x"]
    # redundant raw json columns are not leaked
    assert not any(k.endswith("_json") for k in row)


# ---------------------------------------------------------------------------
# Acceptance #2 -- filterable
# ---------------------------------------------------------------------------

def test_posture_filter_returns_only_matching(trace_client):
    client, _, ledger = trace_client
    _record(ledger, ref="a", posture="blocked")
    _record(ledger, ref="b", posture="answerable")
    resp = client.get("/api/trace/gate-results", params={"posture": "blocked"})
    rows = resp.json()["gate_results"]
    assert [r["posture"] for r in rows] == ["blocked"]


def test_limit_is_clamped_to_max(trace_client):
    client, _, ledger = trace_client
    for i in range(5):
        _record(ledger, ref=f"r{i}", posture="answerable")
    # request beyond MAX_LIMIT must not error and returns all available rows
    resp = client.get("/api/trace/gate-results", params={"limit": 10000})
    assert resp.status_code == 200
    assert len(resp.json()["gate_results"]) == 5


def test_limit_bounds_count(trace_client):
    client, _, ledger = trace_client
    for i in range(3):
        _record(ledger, ref=f"r{i}", posture="answerable")
    resp = client.get("/api/trace/gate-results", params={"limit": 2})
    assert len(resp.json()["gate_results"]) == 2


# ---------------------------------------------------------------------------
# Acceptance #3 -- single-record lookup
# ---------------------------------------------------------------------------

def test_single_record_found(trace_client):
    client, _, ledger = trace_client
    stored = _record(ledger, ref="a", posture="bounded")
    gid = stored["gate_result_id"]
    resp = client.get(f"/api/trace/gate-results/{gid}")
    assert resp.status_code == 200
    assert resp.json()["gate_result_id"] == gid


def test_single_record_unknown_is_404(trace_client):
    client, _, _ = trace_client
    resp = client.get("/api/trace/gate-results/nope")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Acceptance #4 -- read-only / no canon grant
# ---------------------------------------------------------------------------

def test_get_performs_no_db_writes(trace_client, monkeypatch):
    client, db_conn, ledger = trace_client
    _record(ledger, ref="a", posture="answerable")

    def _boom(*a, **k):
        raise AssertionError("trace ledger route must not execute writes")

    monkeypatch.setattr(db_conn, "execute", _boom, raising=False)
    monkeypatch.setattr(db_conn, "executemany", _boom, raising=False)
    resp = client.get("/api/trace/gate-results")
    assert resp.status_code == 200
    assert len(resp.json()["gate_results"]) == 1


def test_canon_eligible_never_exposed_true(trace_client):
    client, _, ledger = trace_client
    # embed a forged canon_eligible inside the persisted snapshot blob
    ledger.record_gate_result(
        {"context_pack_id": "ctx-z", "operation": "answer_context",
         "actor_id": "reader", "canon_eligible": True},
        {"posture": "answerable", "canon_eligible": True},
    )
    list_resp = client.get("/api/trace/gate-results").json()["gate_results"]
    assert list_resp, "expected the seeded row"

    def _assert_no_true(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "canon_eligible":
                    assert v is False
                _assert_no_true(v)
        elif isinstance(node, list):
            for v in node:
                _assert_no_true(v)

    for row in list_resp:
        _assert_no_true(row)
    gid = list_resp[0]["gate_result_id"]
    _assert_no_true(client.get(f"/api/trace/gate-results/{gid}").json())

import importlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def event_sync_client(tmp_path, monkeypatch):
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


def _refresh_payload():
    return {
        "node_id": "NODE:missing",
        "refresh_type": "review",
        "amount": 0.1,
        "reason": "Operator boundary test refresh event.",
        "actor": "local_operator",
    }


def _planar_fact_payload():
    return {
        "plane_path": "test.field.node",
        "r": 1.0,
        "d": 0,
        "q": 0.8,
        "c": 0.7,
        "context_ref": "test",
        "m": "contain",
    }


def _escalation_payload():
    return {
        "plane": "verification",
        "severity": "high",
        "owner": "local_operator",
        "supervisor": "custodian",
    }


def test_event_sync_mutation_routes_require_operator(event_sync_client):
    client, _db, _library = event_sync_client
    probes = [
        ("POST", "/api/coherence/refresh-events", _refresh_payload()),
        ("PATCH", "/api/conflicts/1/acknowledge", None),
        ("POST", "/api/escalation/registry", _escalation_payload()),
        ("POST", "/api/escalation/run/NODE:missing", None),
        ("POST", "/api/escalation/run-all", None),
        ("POST", "/api/nodes/test.field.node", _planar_fact_payload()),
        ("POST", "/api/dcns/sync", None),
    ]
    for method, path, payload in probes:
        res = client.request(method, path, json=payload)
        assert res.status_code in (401, 403), path


def test_authenticated_coherence_conflict_node_and_dcns_paths(event_sync_client):
    client, db, _library = event_sync_client

    refresh = client.post("/api/coherence/refresh-events", json=_refresh_payload(), headers=_auth())
    assert refresh.status_code == 400
    assert "node not found" in refresh.text

    db.execute(
        "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, acknowledged) VALUES (?,?,?,?,?,?)",
        ("test_conflict", "a,b", "boundary", "test.field", int(time.time()), 0),
    )
    row = db.fetchone("SELECT rowid FROM conflicts WHERE term=?", ("boundary",))
    ack = client.patch(f"/api/conflicts/{row['rowid']}/acknowledge", headers=_auth())
    assert ack.status_code == 200
    assert ack.json()["acknowledged"] is True

    node = client.post("/api/nodes/test.field.node", json=_planar_fact_payload(), headers=_auth())
    assert node.status_code == 200
    assert node.json()["stored"] is True

    dcns = client.post("/api/dcns/sync", headers=_auth())
    assert dcns.status_code == 200
    assert dcns.json()["status"] == "ok"


def test_authenticated_escalation_routes_reach_existing_behavior(event_sync_client):
    client, _db, _library = event_sync_client

    registry = client.post("/api/escalation/registry", json=_escalation_payload(), headers=_auth())
    assert registry.status_code == 200
    assert registry.json()["ok"] is True

    run = client.post("/api/escalation/run/NODE:missing", headers=_auth())
    assert run.status_code == 404
    assert "node not found" in run.text

    run_all = client.post("/api/escalation/run-all", headers=_auth())
    assert run_all.status_code == 200
    assert run_all.json()["ok"] is True

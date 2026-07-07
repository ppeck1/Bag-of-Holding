import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def topology_client(tmp_path, monkeypatch):
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


def _card_payload(topic):
    return {
        "plane": "informational",
        "topic": topic,
        "card_type": "constraint",
        "d": 0,
        "m": "contain",
        "constraints": {"test_constraint": True},
    }


def test_topology_mutation_routes_require_operator(topology_client):
    client, _db, _library = topology_client

    probes = [
        (
            "/api/feedback/rewrite",
            {
                "feedback_kind": "reinforcing",
                "action": "create_constraint",
                "reason": "Unauthenticated feedback rewrite should be rejected.",
                "actor": "local_operator",
                "constraint_target": "Unauthorized constraint",
            },
        ),
        (
            "/api/feedback/rewrites/FR_missing/revert",
            {"actor": "local_operator", "reason": "Unauthorized revert should be rejected."},
        ),
        (
            "/api/lattice/edges",
            {
                "source_id": "CARD:missing-source",
                "target_id": "CARD:missing-target",
                "relation": "depends_on",
            },
        ),
    ]
    for path, payload in probes:
        res = client.post(path, json=payload)
        assert res.status_code in (401, 403), path


def test_authenticated_feedback_rewrite_and_revert_still_work(topology_client):
    client, _db, _library = topology_client

    created = client.post(
        "/api/feedback/rewrite",
        json={
            "feedback_kind": "reinforcing",
            "action": "create_constraint",
            "reason": "Operator reviewed feedback creates a reversible constraint.",
            "actor": "local_operator",
            "constraint_target": "Operator boundary test constraint",
        },
        headers=_auth(),
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["ok"] is True
    rewrite_id = payload["rewrite_id"]

    reverted = client.post(
        f"/api/feedback/rewrites/{rewrite_id}/revert",
        json={"actor": "local_operator", "reason": "Operator verified revert."},
        headers=_auth(),
    )
    assert reverted.status_code == 200
    assert reverted.json()["reverted"] is True


def test_authenticated_lattice_edge_creation_still_works(topology_client):
    client, _db, _library = topology_client

    source = client.post("/api/planes/cards", json=_card_payload("Source constraint"), headers=_auth())
    target = client.post("/api/planes/cards", json=_card_payload("Target constraint"), headers=_auth())
    assert source.status_code == 200
    assert target.status_code == 200

    source_id = source.json()["card"]["id"]
    target_id = target.json()["card"]["id"]
    edge = client.post(
        "/api/lattice/edges",
        json={
            "source_id": source_id,
            "target_id": target_id,
            "relation": "depends_on",
            "weight": 1.0,
            "created_by": "local_operator",
        },
        headers=_auth(),
    )
    assert edge.status_code == 200
    payload = edge.json()
    assert payload["ok"] is True
    assert payload["edge"]["relation"] == "depends_on"

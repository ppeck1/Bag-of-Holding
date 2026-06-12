import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def temporal_client(tmp_path, monkeypatch):
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


def _open_item_payload(**overrides):
    payload = {
        "plane_boundary": "evidence|verification",
        "resolution_authority": "local_operator",
        "drift_priority": "moderate",
        "description": "Temporal boundary test ambiguity.",
    }
    payload.update(overrides)
    return payload


def test_temporal_mutation_routes_require_operator(temporal_client):
    client, _db, _library = temporal_client
    probes = [
        ("/api/temporal/re-anchor", {"node_id": "NODE:missing", "actor": "local_operator"}),
        (
            "/api/temporal/resume",
            {
                "anchor_id": "ANC_missing",
                "active_plane": "verification",
                "actor": "local_operator",
                "promotion_reason": "Unauthorized resume should be rejected.",
            },
        ),
        ("/api/temporal/open-items", _open_item_payload()),
        ("/api/temporal/open-items/expire-stale", {}),
        (
            "/api/temporal/open-items/OI_missing/resolve",
            {"resolved_by": "local_operator", "resolution_note": "Unauthorized resolve should be rejected."},
        ),
    ]
    for path, payload in probes:
        res = client.post(path, json=payload)
        assert res.status_code in (401, 403), path


def test_authenticated_open_item_create_expire_and_resolve_work(temporal_client):
    client, _db, _library = temporal_client

    created = client.post("/api/temporal/open-items", json=_open_item_payload(), headers=_auth())
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["status"] == "open"

    resolved = client.post(
        f"/api/temporal/open-items/{item['id']}/resolve",
        json={"resolved_by": "local_operator", "resolution_note": "Operator resolved the simple item."},
        headers=_auth(),
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    expired_item = client.post(
        "/api/temporal/open-items",
        json=_open_item_payload(
            description="Expired temporal boundary test ambiguity.",
            valid_until="2000-01-01T00:00:00+00:00",
        ),
        headers=_auth(),
    )
    assert expired_item.status_code == 200

    expired = client.post("/api/temporal/open-items/expire-stale", headers=_auth())
    assert expired.status_code == 200
    assert expired.json()["expired_count"] >= 1


def test_authenticated_reanchor_and_resume_reach_existing_validation(temporal_client):
    client, _db, _library = temporal_client

    reanchor = client.post(
        "/api/temporal/re-anchor",
        json={"node_id": "NODE:missing", "actor": "local_operator"},
        headers=_auth(),
    )
    assert reanchor.status_code == 400
    assert "node not found" in reanchor.text

    resume = client.post(
        "/api/temporal/resume",
        json={
            "anchor_id": "ANC_missing",
            "active_plane": "verification",
            "actor": "local_operator",
            "promotion_reason": "Operator request reaches anchor validation.",
        },
        headers=_auth(),
    )
    assert resume.status_code == 400
    assert "anchor event not found" in resume.text

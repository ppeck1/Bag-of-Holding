import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def artifact_client(tmp_path, monkeypatch):
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


def _seed_review_source(db, library):
    rel_path = "notes/review-source.md"
    path = library / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "boh:\n"
        "  id: review-source\n"
        "  status: draft\n"
        "  type: note\n"
        "  purpose: Review Source\n"
        "---\n\n"
        "# Review Source\n\nTerm: bounded artifact generation.\n",
        encoding="utf-8",
    )
    db.execute(
        "INSERT OR REPLACE INTO docs (doc_id, path, title, status) VALUES (?,?,?,?)",
        ("review-source", rel_path, "Review Source", "draft"),
    )
    return rel_path, path.with_suffix(".review.json")


def test_artifact_mutation_routes_require_operator(artifact_client):
    client, db, library = artifact_client
    rel_path, _artifact_path = _seed_review_source(db, library)

    plane = client.post(
        "/api/plane-interfaces",
        json={
            "source_plane": "review",
            "target_plane": "canonical",
            "translation_reason": "Unauthorized interface creation must be rejected.",
            "certificate_refs": ["missing-cert"],
        },
    )
    assert plane.status_code in (401, 403)

    post_review = client.post(f"/api/review/{rel_path}/regenerate")
    assert post_review.status_code in (401, 403)

    get_review = client.get("/api/review", params={"path": rel_path})
    assert get_review.status_code in (401, 403)

    forced_review = client.get("/api/review", params={"path": rel_path, "force": "true"})
    assert forced_review.status_code in (401, 403)


def test_authenticated_review_generation_and_existing_read_work(artifact_client):
    client, db, library = artifact_client
    rel_path, artifact_path = _seed_review_source(db, library)

    generated = client.get("/api/review", params={"path": rel_path}, headers=_auth())
    assert generated.status_code == 200
    assert generated.json()["_status"] == "generated"
    assert artifact_path.exists()

    existing = client.get("/api/review", params={"path": rel_path})
    assert existing.status_code == 200
    assert existing.json()["_status"] == "existing"

    regenerated = client.post(f"/api/review/{rel_path}/regenerate", headers=_auth())
    assert regenerated.status_code == 200
    assert regenerated.json()["_status"] == "regenerated"


def test_authenticated_plane_interface_reaches_existing_validation(artifact_client):
    client, _db, _library = artifact_client

    res = client.post(
        "/api/plane-interfaces",
        json={
            "source_plane": "review",
            "target_plane": "canonical",
            "translation_reason": "Operator authenticated interface creation reaches validation.",
            "certificate_refs": ["missing-cert"],
        },
        headers=_auth(),
    )
    assert res.status_code == 400
    assert "missing-cert" in res.text

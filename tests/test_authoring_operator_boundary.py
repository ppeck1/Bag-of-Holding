import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def authoring_client(tmp_path, monkeypatch):
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


def _seed_doc(db, library):
    rel_path = "notes/editor-doc.md"
    doc_path = library / rel_path
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        "---\n"
        "boh:\n"
        "  id: editor-doc\n"
        "  status: draft\n"
        "  type: note\n"
        "---\n\n"
        "# Original\n\nOriginal body for editor route tests.\n",
        encoding="utf-8",
    )
    db.execute(
        "INSERT OR REPLACE INTO docs (doc_id, path, title, summary, status) VALUES (?,?,?,?,?)",
        ("editor-doc", rel_path, "Original", "Original summary", "draft"),
    )
    return rel_path, doc_path


def test_editor_mutation_routes_require_operator(authoring_client):
    client, db, library = authoring_client
    _seed_doc(db, library)

    probes = [
        ("PATCH", "/api/editor/editor-doc", {"title": "Nope"}),
        ("POST", "/api/editor/editor-doc/save", None),
        ("DELETE", "/api/editor/editor-doc/draft", None),
        ("POST", "/api/editor/editor-doc/summary/regenerate", None),
    ]
    for method, path, payload in probes:
        res = client.request(method, path, json=payload)
        assert res.status_code in (401, 403), path


def test_authenticated_editor_save_flow_still_works(authoring_client):
    client, db, library = authoring_client
    _rel_path, doc_path = _seed_doc(db, library)

    opened = client.get("/api/editor/editor-doc")
    assert opened.status_code == 200

    patched = client.patch(
        "/api/editor/editor-doc",
        json={"title": "Updated", "body_text": "# Updated\n\nChanged body text."},
        headers=_auth(),
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Updated"

    summary = client.post("/api/editor/editor-doc/summary/regenerate", headers=_auth())
    assert summary.status_code == 200
    assert "summary" in summary.json()

    saved = client.post("/api/editor/editor-doc/save", headers=_auth())
    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    assert "Changed body text" in doc_path.read_text(encoding="utf-8")

    discarded = client.delete("/api/editor/editor-doc/draft", headers=_auth())
    assert discarded.status_code == 200
    assert discarded.json()["discarded"] is True

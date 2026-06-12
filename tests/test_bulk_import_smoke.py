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


def _md(doc_id, title):
    return f"""---
boh:
  id: "{doc_id}"
  document_id: "{doc_id}"
  title: "{title}"
  type: "note"
  document_class: "note"
  status: "draft"
  canonical_layer: "supporting"
  authority_state: "draft"
  review_state: "none"
  project: "Bulk Smoke"
  version: "1.0.0"
  updated: "2026-05-19T00:00:00+00:00"
  source_hash: "seed-{doc_id}"
  provenance:
    mode: "bulk_smoke"
    source: "test"
  topics: ["bulk-smoke"]
  scope:
    plane_scope: ["bulk"]
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: "observe"
    operator_intent: "capture"
    next_operator: null
---

# {title}

Body for {title}.
"""


def test_bulk_import_counts_paths_open_and_html_extraction(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, _library):
        files = [
            ("files", ("root.md", _md("bulk-root-md", "Root Markdown"), "text/markdown")),
            ("files", ("root.html", "<html><head><title>Root HTML</title></head><body><h1>Root Heading</h1><a href='https://example.test'>link</a><table><tr><th>A</th></tr><tr><td>B</td></tr></table></body></html>", "text/html")),
            ("files", ("nested/nested.md", _md("bulk-nested-md", "Nested Markdown"), "text/markdown")),
            ("files", ("nested/nested.html", "<html><head><title>Nested HTML</title></head><body><h2>Nested Heading</h2><a href='/local'>local</a><table><tr><td>x</td></tr></table></body></html>", "text/html")),
        ]
        res = client.post("/api/input/upload", data={"target_folder": "imports/bulk_smoke"}, files=files, headers=_auth())
        assert res.status_code == 200
        payload = res.json()
        assert len(payload["saved"]) == 4
        assert payload["rejected"] == []
        assert sum(1 for item in payload["saved"] if item["indexed"]) == 4
        assert any(item["path"] == "imports/bulk_smoke/nested/nested.md" for item in payload["saved"])
        assert any(item["path"] == "imports/bulk_smoke/nested/nested.html" for item in payload["saved"])

        md = client.get("/api/docs/bulk-root-md/content")
        assert md.status_code == 200
        assert "Root Markdown" in md.text

        html_doc = db.fetchone("SELECT title, summary, path FROM docs WHERE path = ?", ("imports/bulk_smoke/root.html",))
        assert html_doc
        assert "Root HTML" in html_doc["title"]
        fts = db.fetchone("SELECT content FROM docs_fts WHERE path = ?", ("imports/bulk_smoke/root.html",))
        assert fts
        assert "Root Heading" in fts["content"]
        assert "https://example.test" in fts["content"]
        assert "| A |" in fts["content"] or "| --- |" in fts["content"]
        assert "html_extraction" in fts["content"]

        repeat = client.post("/api/input/upload", data={"target_folder": "imports/bulk_smoke"}, files=files, headers=_auth())
        assert repeat.status_code == 200
        repeat_payload = repeat.json()
        assert sum(1 for item in repeat_payload["saved"] if item.get("skipped")) == 4

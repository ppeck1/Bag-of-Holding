from __future__ import annotations

import importlib
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


@contextmanager
def _client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))

    import app.db.connection as db

    db.DB_PATH = str(db_path)
    db.init_db()

    import app.api.main as main

    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, library


def _doc(doc_id: str, title: str, body: str) -> str:
    return f"""---
boh:
  id: "{doc_id}"
  document_id: "{doc_id}"
  title: "{title}"
  purpose: "{title}"
  type: "note"
  document_class: "note"
  status: "draft"
  canonical_layer: "supporting"
  authority_state: "draft"
  review_state: "none"
  project: "Logical Library Test"
  version: "1.0.0"
  updated: "2026-06-19T00:00:00+00:00"
  source_hash: "seed-{doc_id}"
  provenance:
    mode: "test"
    source: "logical-library-test"
  scope:
    plane_scope: ["test"]
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: "observe"
    operator_intent: "capture"
    next_operator: null
---

# {title}

{body}
"""


def _write_and_index(library: Path, rel: str, doc_id: str, title: str, body: str) -> None:
    path = library / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_doc(doc_id, title, body), encoding="utf-8")
    from app.services.indexer import index_file

    result = index_file(path, library)
    assert result["indexed"] is True


def _library_id(body: dict, name: str) -> str:
    matches = [lib["id"] for lib in body["libraries"] if lib["name"] == name]
    assert len(matches) == 1, body
    return matches[0]


def _auth_headers() -> dict[str, str]:
    return {"X-BOH-Operator-Token": "test-token"}


def test_libraries_are_derived_from_visible_indexed_paths(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, library):
        _write_and_index(library, "alpha/a.md", "alpha-doc", "Alpha Doc", "alpha sharedneedle")
        _write_and_index(library, "beta/b.md", "beta-doc", "Beta Doc", "beta sharedneedle")
        _write_and_index(library, "root.md", "root-doc", "Root Doc", "root sharedneedle")

        response = client.get("/api/libraries")
        assert response.status_code == 200
        body = response.json()
        by_name = {lib["name"]: lib for lib in body["libraries"]}

        assert by_name["All libraries"]["id"] == "all"
        assert by_name["All libraries"]["count"] == 3
        assert by_name["Unfiled"]["id"] == "unfiled"
        assert by_name["Unfiled"]["count"] == 1
        assert by_name["alpha"]["count"] == 1
        assert by_name["beta"]["count"] == 1


def test_docs_search_and_cards_filter_by_logical_library(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, library):
        _write_and_index(library, "alpha/a.md", "alpha-doc", "Alpha Doc", "alpha sharedneedle")
        _write_and_index(library, "beta/b.md", "beta-doc", "Beta Doc", "beta sharedneedle")
        _write_and_index(library, "root.md", "root-doc", "Root Doc", "root sharedneedle")

        libraries = client.get("/api/libraries").json()
        alpha_id = _library_id(libraries, "alpha")
        beta_id = _library_id(libraries, "beta")

        all_docs = client.get("/api/docs?per_page=50")
        assert all_docs.status_code == 200
        assert {d["doc_id"] for d in all_docs.json()["docs"]} == {
            "alpha-doc", "beta-doc", "root-doc"
        }

        alpha_docs = client.get(f"/api/docs?library_id={alpha_id}&per_page=50")
        assert alpha_docs.status_code == 200
        assert [d["doc_id"] for d in alpha_docs.json()["docs"]] == ["alpha-doc"]

        unfiled_docs = client.get("/api/docs?library_id=unfiled&per_page=50")
        assert unfiled_docs.status_code == 200
        assert [d["doc_id"] for d in unfiled_docs.json()["docs"]] == ["root-doc"]

        alpha_search = client.get(f"/api/search?q=sharedneedle&library_id={alpha_id}&limit=10")
        assert alpha_search.status_code == 200
        assert [r["doc_id"] for r in alpha_search.json()["results"]] == ["alpha-doc"]

        beta_search = client.get(f"/api/search?q=sharedneedle&library_id={beta_id}&limit=10")
        assert beta_search.status_code == 200
        assert [r["doc_id"] for r in beta_search.json()["results"]] == ["beta-doc"]

        alpha_cards = client.get(f"/api/planes/cards?library_id={alpha_id}&limit=50")
        assert alpha_cards.status_code == 200
        assert [c["doc_id"] for c in alpha_cards.json()["cards"]] == ["alpha-doc"]


def test_fold_and_graph_filter_by_logical_library(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, library):
        _write_and_index(library, "alpha/a.md", "alpha-doc", "Alpha Doc", "alpha sharedneedle")
        _write_and_index(library, "beta/b.md", "beta-doc", "Beta Doc", "beta sharedneedle")
        _write_and_index(library, "root.md", "root-doc", "Root Doc", "root sharedneedle")

        libraries = client.get("/api/libraries").json()
        alpha_id = _library_id(libraries, "alpha")

        alpha_fold = client.get(f"/api/fold/library?library_id={alpha_id}&limit=50")
        assert alpha_fold.status_code == 200
        assert alpha_fold.json()["library"]["id"] == alpha_id
        assert [d["doc_id"] for d in alpha_fold.json()["docs"]] == ["alpha-doc"]

        unfiled_fold = client.get("/api/fold/library?library_id=unfiled&limit=50")
        assert unfiled_fold.status_code == 200
        assert [d["doc_id"] for d in unfiled_fold.json()["docs"]] == ["root-doc"]

        graph = client.get(f"/api/graph/projection?mode=web&max_nodes=10&library_id={alpha_id}")
        assert graph.status_code == 200
        assert {n["id"] for n in graph.json()["nodes"]} == {"alpha-doc"}
        assert all(e["source"] == "alpha-doc" and e["target"] == "alpha-doc" for e in graph.json()["edges"]) or not graph.json()["edges"]

        cluster = client.get(
            f"/api/fold/cluster/project/Logical%20Library%20Test?library_id={alpha_id}"
        )
        assert cluster.status_code == 200
        assert cluster.json()["aggregation"]["inputs_count"] == 1
        assert {c["scope_id"] for c in cluster.json()["contributors"]} == {"alpha-doc"}

        corpus = client.get(f"/api/fold/corpus/project?library_id={alpha_id}")
        assert corpus.status_code == 200
        assert corpus.json()["aggregation"]["inputs_count"] == 1
        assert {c["scope_id"] for c in corpus.json()["contributors"]} == {
            "project:Logical Library Test"
        }

        node = client.get(f"/api/fold/node/alpha-doc?library_id={alpha_id}")
        assert node.status_code == 200
        out_of_scope = client.get("/api/fold/node/beta-doc?library_id=" + alpha_id)
        assert out_of_scope.status_code == 404


def test_invalid_library_id_fails_closed(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, library):
        _write_and_index(library, "alpha/a.md", "alpha-doc", "Alpha Doc", "alpha sharedneedle")

        for path in (
            "/api/docs?library_id=missing",
            "/api/search?q=sharedneedle&library_id=missing",
            "/api/planes/cards?library_id=missing",
            "/api/fold/library?library_id=missing",
            "/api/fold/node/alpha-doc?library_id=missing",
            "/api/fold/cluster/project/Logical%20Library%20Test?library_id=missing",
            "/api/fold/corpus/project?library_id=missing",
            "/api/graph/projection?mode=web&max_nodes=10&library_id=missing",
        ):
            response = client.get(path)
            assert response.status_code == 400
            assert "Unknown logical library" in response.json()["detail"]


def test_library_display_overrides_persist_without_changing_filtering(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, library):
        _write_and_index(library, "alpha/a.md", "alpha-doc", "Alpha Doc", "alpha sharedneedle")
        _write_and_index(library, "beta/b.md", "beta-doc", "Beta Doc", "beta sharedneedle")

        libraries = client.get("/api/libraries").json()
        alpha_id = _library_id(libraries, "alpha")

        response = client.patch(
            f"/api/libraries/{alpha_id}",
            json={"display_name": "Alpha Shelf", "hidden": True, "sort_order": 5},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert response.json()["library"]["name"] == "Alpha Shelf"
        assert response.json()["library"]["derived_name"] == "alpha"
        assert response.json()["library"]["hidden"] is True

        dropdown = client.get("/api/libraries").json()
        assert alpha_id not in {lib["id"] for lib in dropdown["libraries"]}

        managed = client.get("/api/libraries?include_hidden=true").json()
        by_id = {lib["id"]: lib for lib in managed["libraries"]}
        assert by_id[alpha_id]["name"] == "Alpha Shelf"
        assert by_id[alpha_id]["hidden"] is True
        assert by_id[alpha_id]["overridden"] is True

        alpha_docs = client.get(f"/api/docs?library_id={alpha_id}&per_page=50")
        assert alpha_docs.status_code == 200
        assert [d["doc_id"] for d in alpha_docs.json()["docs"]] == ["alpha-doc"]


def test_library_order_and_reset_are_presentation_only(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, library):
        _write_and_index(library, "alpha/a.md", "alpha-doc", "Alpha Doc", "alpha sharedneedle")
        _write_and_index(library, "beta/b.md", "beta-doc", "Beta Doc", "beta sharedneedle")
        _write_and_index(library, "root.md", "root-doc", "Root Doc", "root sharedneedle")

        libraries = client.get("/api/libraries?include_hidden=true").json()
        alpha_id = _library_id(libraries, "alpha")
        beta_id = _library_id(libraries, "beta")

        response = client.patch(
            "/api/libraries/order",
            json={"ids": ["all", beta_id, "unfiled", alpha_id]},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        ordered = [lib["id"] for lib in client.get("/api/libraries").json()["libraries"]]
        assert ordered[:4] == ["all", beta_id, "unfiled", alpha_id]

        renamed = client.patch(
            f"/api/libraries/{beta_id}",
            json={"display_name": "Beta Shelf"},
            headers=_auth_headers(),
        )
        assert renamed.status_code == 200
        assert renamed.json()["library"]["name"] == "Beta Shelf"

        reset = client.delete(f"/api/libraries/{beta_id}/override", headers=_auth_headers())
        assert reset.status_code == 200
        assert reset.json()["library"]["name"] == "beta"
        assert reset.json()["library"]["overridden"] is False


def test_library_mutation_routes_require_operator_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")
    with _client(tmp_path, monkeypatch) as (client, library):
        _write_and_index(library, "alpha/a.md", "alpha-doc", "Alpha Doc", "alpha sharedneedle")
        alpha_id = _library_id(client.get("/api/libraries").json(), "alpha")

        missing = client.patch(f"/api/libraries/{alpha_id}", json={"display_name": "Nope"})
        assert missing.status_code == 401

        wrong = client.patch(
            f"/api/libraries/{alpha_id}",
            json={"display_name": "Nope"},
            headers={"X-BOH-Operator-Token": "wrong"},
        )
        assert wrong.status_code == 403

        ok = client.patch(
            f"/api/libraries/{alpha_id}",
            json={"display_name": "Alpha Shelf"},
            headers=_auth_headers(),
        )
        assert ok.status_code == 200


def test_all_library_cannot_be_hidden(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, library):
        _write_and_index(library, "alpha/a.md", "alpha-doc", "Alpha Doc", "alpha sharedneedle")

        response = client.patch(
            "/api/libraries/all",
            json={"hidden": True},
            headers=_auth_headers(),
        )
        assert response.status_code == 422
        assert "all cannot be hidden" in response.json()["detail"]

from __future__ import annotations

import importlib
import re
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


UI_SOURCE = Path(__file__).parents[1] / "app" / "ui2" / "js" / "screens" / "search-context.js"
NEEDLE = "eligibilitystarvationneedle"


@contextmanager
def _client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.delenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", raising=False)

    import app.db.connection as db

    db.DB_PATH = str(db_path)
    db.init_db()

    import app.api.main as main

    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db, library


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
  project: "Search Filtering Contract"
  version: "1.0.0"
  updated: "2026-07-10T00:00:00+00:00"
  source_hash: "seed-{doc_id}"
  provenance:
    mode: "test"
    source: "search-filtering-contract"
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


def _index(library: Path, rel: str, doc_id: str, *, strong: bool) -> None:
    path = library / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ((NEEDLE + " ") * 40) if strong else (NEEDLE + " " + ("filler " * 300))
    path.write_text(_doc(doc_id, doc_id, body), encoding="utf-8")
    from app.services.indexer import index_file

    assert index_file(path, library)["indexed"] is True


def _library_id(client: TestClient, name: str) -> str:
    libraries = client.get("/api/libraries").json()["libraries"]
    matches = [item["id"] for item in libraries if item["name"] == name]
    assert len(matches) == 1, libraries
    return matches[0]


def test_logical_library_eligibility_precedes_keyword_candidate_limit(tmp_path, monkeypatch):
    """>2*limit stronger out-of-library matches must not starve an eligible result."""
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        for index in range(3):
            _index(library, f"outside/distractor-{index}.md", f"outside-{index}", strong=True)
        _index(library, "target/eligible.md", "target-eligible", strong=False)

        target_library = _library_id(client, "target")
        response = client.get(
            "/api/search",
            params={"q": NEEDLE, "library_id": target_library, "limit": 1},
        )

        assert response.status_code == 200
        assert not any("error" in item for item in response.json()["results"]), response.json()["results"]
        assert [item["doc_id"] for item in response.json()["results"]] == ["target-eligible"]


def test_promoted_eligibility_precedes_keyword_candidate_limit(tmp_path, monkeypatch):
    """>2*limit stronger promoted matches must not starve a visible normal result."""
    with _client(tmp_path, monkeypatch) as (client, db, library):
        for index in range(3):
            doc_id = f"promoted-{index}"
            _index(library, f"promoted_intake/{doc_id}.md", doc_id, strong=True)
            db.execute(
                "UPDATE docs SET corpus_class = 'CORPUS_CLASS:PROMOTED_INTAKE' WHERE doc_id = ?",
                (doc_id,),
            )
        _index(library, "visible/eligible.md", "visible-eligible", strong=False)

        response = client.get("/api/search", params={"q": NEEDLE, "limit": 1})

        assert response.status_code == 200
        assert not any("error" in item for item in response.json()["results"]), response.json()["results"]
        assert [item["doc_id"] for item in response.json()["results"]] == ["visible-eligible"]


def test_promoted_control_is_truthful_per_search_mode():
    src = UI_SOURCE.read_text(encoding="utf-8")
    keyword_block = src[src.index("function runKeyword"):src.index("function runBrief")]
    brief_block = src[src.index("function runBrief"):src.index("function run()")]
    toggle_at = src.index("Toggle({ checked: _includePromoted")
    toggle_context = src[max(0, toggle_at - 260):toggle_at]

    assert "include_promoted" not in keyword_block
    assert re.search(r"include_promoted\s*:\s*_includePromoted", brief_block)
    assert re.search(r'_mode\s*===\s*["\']brief["\']\s*&&', toggle_context), (
        "The promoted toggle must be hidden in keyword mode because /api/search uses the "
        "server environment gate; Current Context retains the governed request opt-in."
    )

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def inventory_client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")
    monkeypatch.setenv("BOH_DETERMINISTIC_REVIEW_ON_INDEX", "false")

    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()

    import app.core.autoindex as autoindex
    importlib.reload(autoindex)

    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db, library, autoindex


def _auth():
    return {"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": "local_operator"}


def _doc(doc_id: str, title: str | None = None) -> str:
    title = title or doc_id
    return f"""---
boh:
  id: "{doc_id}"
  title: "{title}"
  type: "note"
  status: "draft"
  rubrix:
    operator_state: "observe"
    operator_intent: "capture"
---
# {title}

Body.
"""


def test_autoindex_skips_quarantine_by_default(inventory_client):
    client, db, library, autoindex = inventory_client
    (library / "source.md").write_text(_doc("source-doc"), encoding="utf-8")
    quarantine = library / ".boh_quarantine"
    quarantine.mkdir()
    (quarantine / "quarantined.md").write_text(_doc("quarantined-doc"), encoding="utf-8")

    result = autoindex.run_auto_index(str(library), changed_only=True)
    assert result["indexed"] == 1
    assert any(
        row["relative_path"] == ".boh_quarantine/quarantined.md"
        and row["classification"] == "quarantine"
        and row["action"] == "skipped_excluded"
        for row in result["manifest"]
    )
    assert db.fetchone("SELECT * FROM docs WHERE path = ?", (".boh_quarantine/quarantined.md",)) is None

    report = client.get("/api/autoindex/report").json()
    assert any(
        row["relative_path"] == ".boh_quarantine/quarantined.md"
        and row["classification"] == "quarantine"
        and row["action"] == "skipped_excluded"
        for row in report["manifest"]
    )


def test_autoindex_skips_review_json_by_default(inventory_client):
    client, db, library, autoindex = inventory_client
    (library / "source.md").write_text(_doc("source-doc"), encoding="utf-8")
    (library / "source.review.json").write_text('{"generated": true}', encoding="utf-8")

    result = autoindex.run_auto_index(str(library), changed_only=True)
    assert result["indexed"] == 1
    assert any(
        row["relative_path"] == "source.review.json"
        and row["classification"] == "review_artifact"
        and row["action"] == "skipped_excluded"
        for row in result["manifest"]
    )
    assert db.fetchone("SELECT * FROM docs WHERE path = ?", ("source.review.json",)) is None

    report = client.get("/api/autoindex/report").json()
    assert any(
        row["relative_path"] == "source.review.json"
        and row["classification"] == "review_artifact"
        and row["action"] == "skipped_excluded"
        for row in report["manifest"]
    )


def test_clean_seed_autoindex_indexes_only_primitive_sources(inventory_client):
    client, db, library, _autoindex = inventory_client
    clean = client.post(
        "/api/workspace/reset-full",
        json={"confirm": "RESET", "preserve_canonical": False},
        headers=_auth(),
    )
    assert clean.status_code == 200
    clean_payload = clean.json()
    assert set(clean_payload) >= {
        "files_remaining_total",
        "files_remaining_by_folder",
        "quarantine_files_total",
        "primitive_fixture_files_total",
        "indexed_candidates_total",
        "review_artifact_files_total",
    }

    seed = client.post("/api/workspace/seed-fixtures", json={}, headers=_auth())
    assert seed.status_code == 200
    seed_payload = seed.json()
    expected = seed_payload["expected_source_fixture_count"]
    assert seed_payload["actual_source_fixture_count"] == expected
    assert set(seed_payload) >= {
        "review_artifact_count",
        "indexed_candidate_count",
        "files_created",
        "files_skipped",
        "files_replaced",
    }

    quarantine = library / ".boh_quarantine"
    quarantine.mkdir(exist_ok=True)
    (quarantine / "leftover.md").write_text(_doc("leftover-doc"), encoding="utf-8")
    (library / "fixtures" / "primitive_test" / "valid_markdown.review.json").write_text(
        '{"generated": true}',
        encoding="utf-8",
    )

    run = client.post("/api/autoindex/run", json={"changed_only": True}, headers=_auth())
    assert run.status_code == 200
    run_payload = run.json()
    assert run_payload["failed"] == 0
    assert run_payload["indexed_candidates_total"] == expected

    paths = [row["path"] for row in db.fetchall("SELECT path FROM docs")]
    assert len([p for p in paths if p.startswith("fixtures/primitive_test/")]) == expected
    assert not any(".boh_quarantine/" in p for p in paths)
    assert not any(p.endswith(".review.json") or p.endswith(".review.md") for p in paths)

    report = client.get("/api/autoindex/report").json()
    manifest = report["manifest"]
    assert len(manifest) >= expected + 2
    assert any(row["classification"] == "quarantine" and row["action"] == "skipped_excluded" for row in manifest)
    assert any(row["classification"] == "review_artifact" and row["action"] == "skipped_excluded" for row in manifest)
    assert all(row["classification"] in {
        "fixture", "import", "quarantine", "scratch", "demo", "review_artifact", "unknown"
    } for row in manifest)
    assert all(row["action"] in {
        "indexed", "skipped_excluded", "skipped_unchanged", "failed"
    } for row in manifest)

    state = client.get("/api/workspace/state").json()
    stats = state["stats"]
    assert stats["quarantine_files_total"] == 1
    assert stats["review_artifact_files_total"] == 1
    assert stats["primitive_fixture_files_total"] == expected
    assert stats["indexed_candidates_total"] == expected

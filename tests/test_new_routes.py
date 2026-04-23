"""tests/test_new_routes.py: Phase 2 route tests for Bag of Holding v2.

Tests all six new routes and validates /api/ prefix on all existing routes.
Uses FastAPI TestClient — no live server required.
"""

import json
import os
import tempfile
import pytest

os.environ.setdefault("BOH_DB", os.path.join(os.path.dirname(__file__), "test_boh_v2.db"))
os.environ.setdefault("BOH_LIBRARY", os.path.join(os.path.dirname(__file__), "..", "library"))

from fastapi.testclient import TestClient
from app.api.main import app
from app.db import connection as db

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True, scope="module")
def ensure_db():
    db.init_db()
    # Seed the library so dashboard/docs have data to report
    client.post("/api/index", json={"library_root": os.environ["BOH_LIBRARY"]})


# ── /api/ prefix enforcement ──────────────────────────────────────────────────

def test_old_root_search_returns_404():
    """Old /search path must not exist — only /api/search."""
    r = client.get("/search?q=test")
    assert r.status_code == 404

def test_old_root_canon_returns_404():
    r = client.get("/canon")
    assert r.status_code == 404

def test_old_root_conflicts_returns_404():
    r = client.get("/conflicts")
    assert r.status_code == 404

def test_old_root_workflow_returns_404():
    r = client.get("/workflow")
    assert r.status_code == 404

def test_old_root_index_returns_404_or_405():
    """Old /index POST path must not route to any API handler.
    StaticFiles returns 405 (Method Not Allowed) for POST on a static path — also correct.
    """
    r = client.post("/index", json={})
    assert r.status_code in (404, 405)


# ── Existing routes at /api/ prefix ──────────────────────────────────────────

def test_api_search_responds():
    r = client.get("/api/search?q=planar")
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert "score_formula" in body

def test_api_canon_responds():
    r = client.get("/api/canon?topic=planar")
    assert r.status_code == 200
    body = r.json()
    assert "winner" in body
    assert "candidates" in body
    assert "score_formula" in body

def test_api_conflicts_responds():
    r = client.get("/api/conflicts")
    assert r.status_code == 200
    body = r.json()
    assert "conflicts" in body
    assert "No auto-resolution" in body["note"]

def test_api_workflow_responds():
    r = client.get("/api/workflow")
    assert r.status_code == 200
    body = r.json()
    assert "rubrix_schema" in body
    assert "allowed_transitions" in body["rubrix_schema"]

def test_api_events_responds():
    r = client.get("/api/events")
    assert r.status_code == 200
    assert "events" in r.json()

def test_api_events_ics_responds():
    r = client.get("/api/events/export.ics")
    assert r.status_code == 200
    assert "BEGIN:VCALENDAR" in r.text

def test_api_index_responds():
    r = client.post("/api/index", json={"library_root": os.environ["BOH_LIBRARY"]})
    assert r.status_code == 200
    body = r.json()
    assert "indexed" in body
    assert "conflicts_detected" in body


# ── New route: GET /api/dashboard ────────────────────────────────────────────

def test_api_dashboard_responds():
    r = client.get("/api/dashboard")
    assert r.status_code == 200

def test_api_dashboard_has_required_fields():
    r = client.get("/api/dashboard")
    body = r.json()
    required = {
        "total_docs", "canonical_docs", "draft_docs", "working_docs",
        "archived_docs", "open_conflicts", "acknowledged_conflicts",
        "total_events", "indexed_planes", "last_indexed_ts",
    }
    missing = required - set(body.keys())
    assert not missing, f"Dashboard missing fields: {missing}"

def test_api_dashboard_counts_are_non_negative():
    r = client.get("/api/dashboard")
    body = r.json()
    for key, val in body.items():
        if val is not None and isinstance(val, (int, float)):
            assert val >= 0, f"Dashboard field {key} is negative: {val}"


# ── New route: GET /api/docs (paginated list) ─────────────────────────────────

def test_api_docs_list_responds():
    r = client.get("/api/docs")
    assert r.status_code == 200

def test_api_docs_list_has_pagination_fields():
    r = client.get("/api/docs")
    body = r.json()
    assert "total" in body
    assert "page" in body
    assert "per_page" in body
    assert "docs" in body
    assert isinstance(body["docs"], list)

def test_api_docs_list_default_page_is_1():
    r = client.get("/api/docs")
    assert r.json()["page"] == 1

def test_api_docs_list_filter_by_status():
    r = client.get("/api/docs?status=draft")
    assert r.status_code == 200
    for doc in r.json()["docs"]:
        assert doc["status"] == "draft"

def test_api_docs_single_404_on_missing():
    r = client.get("/api/docs/nonexistent-id-xyz")
    assert r.status_code == 404


# ── New route: GET /api/planes ────────────────────────────────────────────────

def test_api_planes_responds():
    r = client.get("/api/planes")
    assert r.status_code == 200

def test_api_planes_has_count_and_list():
    body = r = client.get("/api/planes").json()
    assert "count" in body
    assert "planes" in body
    assert isinstance(body["planes"], list)


# ── New route: GET /api/health ────────────────────────────────────────────────

def test_api_health_responds():
    r = client.get("/api/health")
    assert r.status_code == 200

def test_api_health_status_ok():
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["version"] == "2.0.0"
    assert body["db"] == "connected"


# ── New route: PATCH /api/conflicts/{rowid}/acknowledge ───────────────────────

def test_api_conflict_acknowledge_404_on_missing():
    r = client.patch("/api/conflicts/999999/acknowledge")
    assert r.status_code == 404

def test_api_conflict_acknowledge_marks_seen_without_deleting():
    """Seed a conflict, acknowledge it, verify record still exists with acknowledged=1."""
    from app.db import connection as _db
    import time
    _db.execute(
        "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, acknowledged) "
        "VALUES (?,?,?,?,?,?)",
        ("test_conflict", "doc-ack-test", "ack-term", "test.plane", int(time.time()), 0),
    )
    row = _db.fetchone(
        "SELECT rowid FROM conflicts WHERE doc_ids='doc-ack-test' AND term='ack-term'"
    )
    assert row, "Seeded conflict not found"
    rowid = row["rowid"]

    r = client.patch(f"/api/conflicts/{rowid}/acknowledge")
    assert r.status_code == 200
    body = r.json()
    assert body["acknowledged"] is True
    assert body["rowid"] == rowid

    # Conflict record still exists
    still_there = _db.fetchone("SELECT acknowledged FROM conflicts WHERE rowid=?", (rowid,))
    assert still_there is not None, "Conflict was deleted — must be preserved"
    assert still_there["acknowledged"] == 1, "acknowledged flag not set"


# ── New route: PATCH /api/workflow/{doc_id} ───────────────────────────────────

def test_api_workflow_transition_404_on_missing():
    r = client.patch("/api/workflow/nonexistent-id-xyz",
                     json={"operator_state": "vessel", "operator_intent": "capture"})
    assert r.status_code == 404

def test_api_workflow_transition_rejects_invalid_state():
    # Get a real doc_id first
    docs = client.get("/api/docs").json()["docs"]
    if not docs:
        pytest.skip("No documents indexed")
    doc_id = docs[0]["doc_id"]
    r = client.patch(f"/api/workflow/{doc_id}",
                     json={"operator_state": "INVALID", "operator_intent": "capture"})
    assert r.status_code == 422

def test_api_workflow_transition_rejects_illegal_jump():
    """Jumping from 'observe' to 'release' skips steps — must be rejected."""
    docs = client.get("/api/docs?operator_state=observe").json()["docs"]
    if not docs:
        pytest.skip("No documents in observe state")
    doc_id = docs[0]["doc_id"]
    r = client.patch(f"/api/workflow/{doc_id}",
                     json={"operator_state": "release", "operator_intent": "canonize"})
    assert r.status_code == 422
    assert "Transition" in r.json()["detail"]

def test_api_workflow_transition_valid_observe_to_vessel():
    docs = client.get("/api/docs?operator_state=observe").json()["docs"]
    if not docs:
        pytest.skip("No documents in observe state")
    doc_id = docs[0]["doc_id"]
    r = client.patch(f"/api/workflow/{doc_id}",
                     json={"operator_state": "vessel", "operator_intent": "triage"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["previous_state"] == "observe"
    assert body["new_state"] == "vessel"


# ── New route: POST /api/ingest/snapshot ──────────────────────────────────────

def test_api_ingest_snapshot_rejects_missing_file():
    r = client.post("/api/ingest/snapshot", json={"path": "/nonexistent/path/file.json"})
    assert r.status_code == 200  # returns error dict, not HTTP error
    assert "error" in r.json()

def test_api_ingest_snapshot_ingests_valid_file():
    data = {
        "run_id": "route-test-001",
        "files": [{
            "artifacts": {
                "meta": {
                    "id": "route-snap-001",
                    "type": "note",
                    "path": "snapshot/route-test.md",
                    "status": "working",
                    "updated": "2024-05-01T00:00:00Z",
                    "topics": ["route test"],
                    "source_type": "snapshot",
                    "rubrix": {"operator_state": "vessel", "operator_intent": "capture"},
                    "scope": {"plane_scope": [], "field_scope": [], "node_scope": []},
                },
                "defs": [], "vars": [], "events": [],
            }
        }],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        r = client.post("/api/ingest/snapshot", json={"path": path})
        assert r.status_code == 200
        body = r.json()
        assert "error" not in body
        assert body.get("inserted_docs") == 1
    finally:
        os.unlink(path)

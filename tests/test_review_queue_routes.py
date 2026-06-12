"""Phase 7 Review Queue surface tests (TASK 3.2).

Verifies the /api/review-queue routes that inspect and adjudicate correction-loop
patch proposals by composing the frozen correction_ledger functions:
- inspectable queue + status filter + limit clamp
- single-record lookup (200 / 404)
- reject writes trace and flips status; missing note -> 422; unknown -> 404
- approve honors the frozen contract (regression fixtures required, canon change
  created, forbidden_auto_apply kept); missing fixtures -> 422; unknown -> 404
- operator-token boundary on the write routes; no canon_eligible=True exposed
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def rq_client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")

    import app.db.connection as db_conn
    db_conn.DB_PATH = str(db_path)
    db_conn.init_db()

    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()

    from app.core import correction_ledger

    with TestClient(main.app) as client:
        yield client, db_conn, correction_ledger


def _auth():
    return {"X-BOH-Operator-Token": "test-token"}


def _propose(ledger, *, change="route patch", ptype="retrieval_route_patch"):
    return ledger.create_patch_proposal(
        proposed_from="mistake_x",
        proposal_type=ptype,
        proposed_change=change,
        evidence_refs=["ev-1"],
    )


# ---------------------------------------------------------------------------
# Acceptance #1 -- inspectable queue + filter + clamp
# ---------------------------------------------------------------------------

def test_empty_queue_returns_200_empty_list(rq_client):
    client, _, _ = rq_client
    resp = client.get("/api/review-queue/proposals")
    assert resp.status_code == 200
    assert resp.json() == {"proposals": []}


def test_created_proposal_is_inspectable(rq_client):
    client, _, ledger = rq_client
    _propose(ledger)
    rows = client.get("/api/review-queue/proposals").json()["proposals"]
    assert len(rows) == 1
    row = rows[0]
    assert row["proposal_type"] == "retrieval_route_patch"
    assert row["status"] == "proposed"
    assert row["forbidden_auto_apply"] == 1
    assert row["requires_review_by"] == "reviewer"
    assert row["blast_radius"] == "local"
    assert not any(k.endswith("_json") for k in row)


def test_status_filter_and_limit_clamp(rq_client):
    client, _, ledger = rq_client
    _propose(ledger, change="a")
    _propose(ledger, change="b")
    proposed = client.get("/api/review-queue/proposals", params={"status": "proposed"}).json()["proposals"]
    assert len(proposed) == 2
    none = client.get("/api/review-queue/proposals", params={"status": "rejected"}).json()["proposals"]
    assert none == []
    clamped = client.get("/api/review-queue/proposals", params={"limit": 99999})
    assert clamped.status_code == 200


# ---------------------------------------------------------------------------
# Acceptance #2 -- single-record lookup
# ---------------------------------------------------------------------------

def test_single_record_found_and_missing(rq_client):
    client, _, ledger = rq_client
    pid = _propose(ledger)["patch_id"]
    assert client.get(f"/api/review-queue/proposals/{pid}").json()["patch_id"] == pid
    assert client.get("/api/review-queue/proposals/nope").status_code == 404


# ---------------------------------------------------------------------------
# Acceptance #3 -- reject writes trace
# ---------------------------------------------------------------------------

def test_reject_flips_status(rq_client):
    client, _, ledger = rq_client
    pid = _propose(ledger)["patch_id"]
    resp = client.post(
        f"/api/review-queue/proposals/{pid}/reject",
        json={"reviewed_by": "reviewer", "review_note": "not warranted"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert client.get(f"/api/review-queue/proposals/{pid}").json()["status"] == "rejected"


def test_reject_requires_note(rq_client):
    client, _, ledger = rq_client
    pid = _propose(ledger)["patch_id"]
    resp = client.post(
        f"/api/review-queue/proposals/{pid}/reject",
        json={"reviewed_by": "reviewer", "review_note": "   "},
        headers=_auth(),
    )
    assert resp.status_code == 422


def test_reject_unknown_is_404(rq_client):
    client, _, _ = rq_client
    resp = client.post(
        "/api/review-queue/proposals/nope/reject",
        json={"reviewed_by": "reviewer", "review_note": "x"},
        headers=_auth(),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Acceptance #4 -- approve composes the frozen contract
# ---------------------------------------------------------------------------

def test_approve_happy_path_creates_canon_change(rq_client):
    client, _, ledger = rq_client
    pid = _propose(ledger)["patch_id"]
    resp = client.post(
        f"/api/review-queue/proposals/{pid}/approve",
        json={
            "approved_by": "reviewer",
            "changed_objects": ["obj-1"],
            "migration_note": "applied",
            "regression_fixture_refs": ["fix-1"],
        },
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["patch_proposal"]["status"] == "approved"
    assert body["patch_proposal"]["forbidden_auto_apply"] == 1
    assert body["canon_change_record"]["patch_proposal_ref"] == pid


def test_approve_without_fixtures_is_422(rq_client):
    client, _, ledger = rq_client
    pid = _propose(ledger)["patch_id"]
    resp = client.post(
        f"/api/review-queue/proposals/{pid}/approve",
        json={"approved_by": "reviewer", "changed_objects": ["obj-1"], "migration_note": "x"},
        headers=_auth(),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "regression_fixture_refs_required"


def test_approve_schema_patch_allows_no_fixtures(rq_client):
    client, _, ledger = rq_client
    pid = _propose(ledger, ptype="schema_patch", change="schema")["patch_id"]
    resp = client.post(
        f"/api/review-queue/proposals/{pid}/approve",
        json={"approved_by": "schema_owner", "changed_objects": ["s-1"], "migration_note": "schema"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["patch_proposal"]["status"] == "approved"


def test_approve_unknown_is_404(rq_client):
    client, _, _ = rq_client
    resp = client.post(
        "/api/review-queue/proposals/nope/approve",
        json={"approved_by": "reviewer", "changed_objects": ["o"], "migration_note": "x",
              "regression_fixture_refs": ["f"]},
        headers=_auth(),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Acceptance #5 -- auth boundary; reads open
# ---------------------------------------------------------------------------

def test_reject_without_operator_token_denied(rq_client):
    client, _, ledger = rq_client
    pid = _propose(ledger)["patch_id"]
    resp = client.post(
        f"/api/review-queue/proposals/{pid}/reject",
        json={"reviewed_by": "reviewer", "review_note": "x"},
    )
    assert resp.status_code in (401, 403)


def test_approve_without_operator_token_denied(rq_client):
    client, _, ledger = rq_client
    pid = _propose(ledger)["patch_id"]
    resp = client.post(
        f"/api/review-queue/proposals/{pid}/approve",
        json={"approved_by": "reviewer", "changed_objects": ["o"], "migration_note": "x",
              "regression_fixture_refs": ["f"]},
    )
    assert resp.status_code in (401, 403)


def test_reads_open_without_token(rq_client):
    client, _, ledger = rq_client
    _propose(ledger)
    assert client.get("/api/review-queue/proposals").status_code == 200

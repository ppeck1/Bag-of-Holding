"""Phase 7 intake layer API and database integration tests.

Verifies:
- GET /api/intake/capabilities returns 200 with list (may be empty)
- GET /api/intake/capabilities/{id} returns 200 or 404
- GET /api/intake/adapters returns 200 with coverage report
- GET /api/intake/safety-lanes returns 200 with lane summary
- GET /api/intake/quarantine returns 200 with list
- POST /api/intake/run returns 401 without operator token
- POST /api/intake/run returns 422 without BOH_DATA_ROOT
- POST /api/intake/run returns 200 with operator token and valid source
- POST /api/intake/run persists capability to DB
- canon_eligible is never exposed as True in any response
- db_writer persists all artifact types without error
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def intake_client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")
    monkeypatch.setenv("BOH_DATA_ROOT", str(data_root))

    import app.db.connection as db_conn
    db_conn.DB_PATH = str(db_path)
    db_conn.init_db()

    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()

    with TestClient(main.app) as client:
        yield client, db_conn, data_root


def _auth():
    return {"X-BOH-Operator-Token": "test-token"}


def _make_source(tmp_path, filename="doc.md", content="# Title\n\nBody text for testing."):
    watch = tmp_path / "watch"
    watch.mkdir(exist_ok=True)
    src = watch / filename
    if isinstance(content, bytes):
        src.write_bytes(content)
    else:
        src.write_text(content, encoding="utf-8")
    return str(src)


# ---------------------------------------------------------------------------
# Read routes — unauthenticated
# ---------------------------------------------------------------------------

def test_capabilities_empty_returns_200(intake_client):
    client, _, _ = intake_client
    resp = client.get("/api/intake/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


def test_capabilities_single_not_found(intake_client):
    client, _, _ = intake_client
    resp = client.get("/api/intake/capabilities/nonexistent-id")
    assert resp.status_code == 404


def test_adapters_returns_200(intake_client):
    client, _, _ = intake_client
    resp = client.get("/api/intake/adapters")
    assert resp.status_code == 200
    data = resp.json()
    assert "coverage_report" in data
    assert "capability_summary" in data


def test_adapters_coverage_has_known_types(intake_client):
    client, _, _ = intake_client
    resp = client.get("/api/intake/adapters")
    data = resp.json()
    report = data["coverage_report"]
    assert "markdown_direct" in str(report) or ".md" in str(report)


def test_safety_lanes_returns_200(intake_client):
    client, _, _ = intake_client
    resp = client.get("/api/intake/safety-lanes")
    assert resp.status_code == 200
    data = resp.json()
    assert "lanes" in data
    assert "total" in data


def test_quarantine_empty_returns_200(intake_client):
    client, _, _ = intake_client
    resp = client.get("/api/intake/quarantine")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


# ---------------------------------------------------------------------------
# POST /api/intake/run — auth boundary
# ---------------------------------------------------------------------------

def test_run_requires_operator_token(intake_client, tmp_path):
    client, _, _ = intake_client
    src = _make_source(tmp_path)
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "b1"},
    )
    assert resp.status_code == 401


def test_run_returns_422_without_data_root(intake_client, monkeypatch, tmp_path):
    client, _, _ = intake_client
    monkeypatch.delenv("BOH_DATA_ROOT", raising=False)
    src = _make_source(tmp_path)
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "b1"},
        headers=_auth(),
    )
    assert resp.status_code == 422


def test_run_returns_422_for_missing_file(intake_client):
    client, _, _ = intake_client
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": "/nonexistent/path/file.md", "batch_id": "b1"},
        headers=_auth(),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/intake/run — success path
# ---------------------------------------------------------------------------

def test_run_success_markdown(intake_client, tmp_path):
    client, _, _ = intake_client
    src = _make_source(tmp_path, "article.md", "# Article\n\nThis is the article body text.")
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "batch01"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "complete"
    assert data["outcome"] == "processed"
    assert data["intake_capability_id"]
    assert data["canon_eligible"] is False


def test_run_idempotent_duplicate_creates_no_new_run(intake_client, tmp_path):
    # WO-1: manual intake is idempotent — a duplicate POST returns the known revision and creates
    # no new run. An explicit retry must go through the replay path, not a re-POST here.
    client, db_conn, _ = intake_client
    src = _make_source(tmp_path, "idem.md", "# Idem\n\nbody content with several words here")
    first = client.post(
        "/api/intake/run", json={"source_ref": src, "batch_id": "bi"}, headers=_auth()).json()
    assert first["status"] == "complete"
    second = client.post(
        "/api/intake/run", json={"source_ref": src, "batch_id": "bi"}, headers=_auth()).json()
    assert second["status"] == "already_seen"
    n = db_conn.fetchone(
        "SELECT COUNT(*) AS n FROM intake_runs WHERE source_revision_id = ?",
        (first["source_revision_id"],))["n"]
    assert n == 1


def test_run_response_never_has_canon_eligible_true(intake_client, tmp_path):
    client, _, _ = intake_client
    src = _make_source(tmp_path, "doc.md", "# Doc\n\nContent for the document body.")
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "batch02"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["canon_eligible"] is False


def test_run_persists_capability_to_db(intake_client, tmp_path):
    client, db_conn, _ = intake_client
    src = _make_source(tmp_path, "persisted.md", "# Persisted\n\nDocument body text content.")
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "batch03"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    cap_id = resp.json()["intake_capability_id"]

    row = db_conn.fetchone(
        "SELECT * FROM intake_capabilities WHERE intake_capability_id = ?", (cap_id,)
    )
    assert row is not None
    assert row["source_ref"] == src
    assert row["canon_eligible"] == 0


def test_run_persists_raw_artifact(intake_client, tmp_path):
    client, db_conn, _ = intake_client
    src = _make_source(tmp_path, "rawtest.md", "# Raw\n\nDocument body text.")
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "batch04"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    cap_id = resp.json()["intake_capability_id"]

    rows = db_conn.fetchall(
        "SELECT * FROM intake_raw_artifacts WHERE intake_capability_id = ?", (cap_id,)
    )
    assert len(rows) >= 1
    assert rows[0]["source_ref"] == src


def test_run_persists_normalized_artifact(intake_client, tmp_path):
    client, db_conn, _ = intake_client
    src = _make_source(tmp_path, "normtest.md", "# Norm\n\nDocument body text here.")
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "batch05"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    cap_id = resp.json()["intake_capability_id"]

    raw_rows = db_conn.fetchall(
        "SELECT * FROM intake_raw_artifacts WHERE intake_capability_id = ?", (cap_id,)
    )
    assert raw_rows
    raw_id = raw_rows[0]["raw_artifact_id"]
    norm_rows = db_conn.fetchall(
        "SELECT * FROM intake_normalized_artifacts WHERE raw_artifact_id = ?", (raw_id,)
    )
    assert len(norm_rows) >= 1


def test_run_capabilities_list_includes_new_entry(intake_client, tmp_path):
    client, _, _ = intake_client
    src = _make_source(tmp_path, "listed.md", "# Listed\n\nDocument body text.")
    client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "batch06"},
        headers=_auth(),
    )
    resp = client.get("/api/intake/capabilities")
    data = resp.json()
    assert data["total"] >= 1
    ids = [item["intake_capability_id"] for item in data["items"]]
    assert len(ids) >= 1


def test_run_html_route_neutralizes(intake_client, tmp_path):
    client, db_conn, _ = intake_client
    src = _make_source(
        tmp_path, "page.html",
        "<html><body><script>evil()</script><p>Safe content here</p></body></html>"
    )
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "batch07"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "complete"
    assert data["canon_eligible"] is False
    # html was neutralized (normalized), not held — verify a normalized artifact exists
    cap_id = data["intake_capability_id"]
    raw = db_conn.fetchone(
        "SELECT raw_artifact_id FROM intake_raw_artifacts WHERE intake_capability_id = ?", (cap_id,))
    norm = db_conn.fetchone(
        "SELECT 1 AS ok FROM intake_normalized_artifacts WHERE raw_artifact_id = ?",
        (raw["raw_artifact_id"],))
    assert norm is not None


def test_run_hold_path(intake_client, tmp_path):
    client, _, _ = intake_client
    src = _make_source(tmp_path, "report.pdf", b"%PDF-1.4 fake")
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "batch08"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "held_or_quarantined"
    assert data["outcome"] == "held"


def test_run_queryable_true_for_long_doc(intake_client, tmp_path):
    client, db_conn, _ = intake_client
    src = _make_source(
        tmp_path, "long.md",
        "# Long Document\n\nThis document has enough content to pass the queryability threshold check."
    )
    resp = client.post(
        "/api/intake/run",
        json={"source_ref": src, "batch_id": "batch09"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "complete"
    # queryability is now derived from the persisted capability (not the run response payload)
    cap = db_conn.fetchone(
        "SELECT queryable FROM intake_capabilities WHERE intake_capability_id = ?",
        (data["intake_capability_id"],))
    assert cap["queryable"] == 1


def test_run_safety_lanes_updates_after_run(intake_client, tmp_path):
    client, _, _ = intake_client
    src = _make_source(tmp_path, "sltest.md", "# SL\n\nBody text for safety lane test.")
    client.post("/api/intake/run", json={"source_ref": src, "batch_id": "batch10"}, headers=_auth())
    resp = client.get("/api/intake/safety-lanes")
    data = resp.json()
    assert data["total"] >= 1


# ---------------------------------------------------------------------------
# db_writer unit tests
# ---------------------------------------------------------------------------

def test_db_writer_write_capability(intake_client, tmp_path):
    _, db_conn, _ = intake_client
    from app.services.intake.capability import initialize_capability
    from app.services.intake import db_writer

    src = _make_source(tmp_path, "writer_test.md", "# Writer test")
    cap = initialize_capability(source_ref=src, batch_id="dbw1").capability

    db_writer.write_capability(cap)
    row = db_conn.fetchone(
        "SELECT * FROM intake_capabilities WHERE intake_capability_id = ?",
        (cap.intake_capability_id,),
    )
    assert row is not None
    assert row["canon_eligible"] == 0
    assert row["source_ref"] == src


def test_db_writer_write_trace_event(intake_client):
    _, db_conn, _ = intake_client
    from app.services.intake import trace as trace_module, db_writer

    te = trace_module.emit("test_event", intake_capability_id="cap-123", detail={"x": 1})
    db_writer.write_trace_event(te)
    row = db_conn.fetchone(
        "SELECT * FROM intake_trace_events WHERE trace_event_id = ?", (te.trace_event_id,)
    )
    assert row is not None
    assert row["event_type"] == "test_event"


# ---------------------------------------------------------------------------
# Helpers shared by disposition tests
# ---------------------------------------------------------------------------

def _insert_capability(db_conn, cap_id: str, safety_lane: str = "quarantine",
                       lifecycle_state: str = "quarantined", canon_eligible: int = 0):
    import datetime, uuid
    db_conn.execute(
        """INSERT INTO intake_capabilities
           (intake_capability_id, source_ref, batch_id, safety_lane,
            lifecycle_state, canon_eligible, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (cap_id, f"/library/{cap_id}.md", "batch-test",
         safety_lane, lifecycle_state, canon_eligible,
         datetime.datetime.utcnow().isoformat()),
    )


def _insert_quarantine_record(db_conn, cap_id: str, qr_id: str | None = None):
    import datetime, uuid
    qr_id = qr_id or f"qr-{uuid.uuid4().hex[:8]}"
    db_conn.execute(
        """INSERT INTO intake_quarantine_records
           (quarantine_record_id, intake_capability_id, quarantine_reason,
            quarantine_category, review_required, created_at)
           VALUES (?,?,?,?,?,?)""",
        (qr_id, cap_id, "test quarantine", "preservation_failure", 1,
         datetime.datetime.utcnow().isoformat()),
    )
    return qr_id


# ---------------------------------------------------------------------------
# TestOperatorDispositionRoute
# ---------------------------------------------------------------------------

class TestOperatorDispositionRoute:
    PATCH = "/api/intake/capabilities/{id}/operator-disposition"

    def url(self, cap_id: str) -> str:
        return self.PATCH.replace("{id}", cap_id)

    def test_missing_token_returns_401(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-a")
        r = client.patch(self.url("cap-a"), json={"action": "hold", "reason": "test"})
        assert r.status_code == 401

    def test_wrong_token_returns_401_or_403(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-b")
        r = client.patch(self.url("cap-b"), json={"action": "hold", "reason": "test"},
                         headers={"X-BOH-Operator-Token": "wrong"})
        assert r.status_code in (401, 403)

    def test_unknown_capability_returns_404(self, intake_client):
        client, _, _ = intake_client
        r = client.patch(self.url("does-not-exist"),
                         json={"action": "hold", "reason": "test"}, headers=_auth())
        assert r.status_code == 404

    def test_invalid_action_returns_422(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-c")
        r = client.patch(self.url("cap-c"),
                         json={"action": "release_all", "reason": "test"}, headers=_auth())
        assert r.status_code == 422

    def test_blank_reason_returns_422(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-d")
        r = client.patch(self.url("cap-d"),
                         json={"action": "hold", "reason": "  "}, headers=_auth())
        assert r.status_code == 422

    def test_hold_quarantined_capability(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-hold", safety_lane="quarantine",
                           lifecycle_state="quarantined")
        r = client.patch(self.url("cap-hold"),
                         json={"action": "hold", "reason": "needs review"}, headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["safety_lane_before"] == "quarantine"
        assert body["safety_lane_after"] == "hold"
        # Verify DB state
        row = db_conn.fetchone(
            "SELECT safety_lane, lifecycle_state FROM intake_capabilities WHERE intake_capability_id = ?",
            ("cap-hold",))
        assert row["safety_lane"] == "hold"
        assert row["lifecycle_state"] == "quarantined"  # lifecycle_state unchanged

    def test_hold_does_not_change_lifecycle_state(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-hl2", safety_lane="quarantine",
                           lifecycle_state="normalized")
        client.patch(self.url("cap-hl2"),
                     json={"action": "hold", "reason": "test"}, headers=_auth())
        row = db_conn.fetchone(
            "SELECT lifecycle_state FROM intake_capabilities WHERE intake_capability_id = ?",
            ("cap-hl2",))
        assert row["lifecycle_state"] == "normalized"

    def test_release_held_capability(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-rel", safety_lane="hold",
                           lifecycle_state="quarantined")
        r = client.patch(self.url("cap-rel"),
                         json={"action": "release", "reason": "cleared"}, headers=_auth())
        assert r.status_code == 200
        row = db_conn.fetchone(
            "SELECT safety_lane, lifecycle_state FROM intake_capabilities WHERE intake_capability_id = ?",
            ("cap-rel",))
        assert row["safety_lane"] == "accept"
        assert row["lifecycle_state"] == "quarantined"  # lifecycle_state unchanged

    def test_release_quarantined_directly(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-rq", safety_lane="quarantine",
                           lifecycle_state="quarantined")
        r = client.patch(self.url("cap-rq"),
                         json={"action": "release", "reason": "false positive"}, headers=_auth())
        assert r.status_code == 200
        row = db_conn.fetchone(
            "SELECT safety_lane FROM intake_capabilities WHERE intake_capability_id = ?",
            ("cap-rq",))
        assert row["safety_lane"] == "accept"

    def test_release_failed_without_force_returns_422(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-fail", safety_lane="quarantine",
                           lifecycle_state="failed")
        r = client.patch(self.url("cap-fail"),
                         json={"action": "release", "reason": "clear"}, headers=_auth())
        assert r.status_code == 422
        # lifecycle_state and safety_lane unchanged
        row = db_conn.fetchone(
            "SELECT safety_lane, lifecycle_state FROM intake_capabilities WHERE intake_capability_id = ?",
            ("cap-fail",))
        assert row["safety_lane"] == "quarantine"
        assert row["lifecycle_state"] == "failed"

    def test_release_failed_with_force_succeeds(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-ff", safety_lane="quarantine",
                           lifecycle_state="failed")
        r = client.patch(self.url("cap-ff"),
                         json={"action": "release", "reason": "operator override", "force": True},
                         headers=_auth())
        assert r.status_code == 200
        row = db_conn.fetchone(
            "SELECT safety_lane FROM intake_capabilities WHERE intake_capability_id = ?",
            ("cap-ff",))
        assert row["safety_lane"] == "accept"

    def test_hold_already_held_is_idempotent(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-idem", safety_lane="hold",
                           lifecycle_state="quarantined")
        r = client.patch(self.url("cap-idem"),
                         json={"action": "hold", "reason": "again"}, headers=_auth())
        assert r.status_code == 200
        assert r.json().get("idempotent") is True

    def test_release_already_released_is_idempotent(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-idem2", safety_lane="accept",
                           lifecycle_state="normalized")
        r = client.patch(self.url("cap-idem2"),
                         json={"action": "release", "reason": "again"}, headers=_auth())
        assert r.status_code == 200
        assert r.json().get("idempotent") is True

    def test_canon_eligible_anomaly_returns_409_no_mutation(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-canon", safety_lane="quarantine",
                           lifecycle_state="quarantined", canon_eligible=1)
        r = client.patch(self.url("cap-canon"),
                         json={"action": "hold", "reason": "test"}, headers=_auth())
        assert r.status_code == 409
        # Capability row must be unchanged
        row = db_conn.fetchone(
            "SELECT safety_lane FROM intake_capabilities WHERE intake_capability_id = ?",
            ("cap-canon",))
        assert row["safety_lane"] == "quarantine"

    def test_audit_event_written_on_hold(self, intake_client):
        client, db_conn, _ = intake_client
        qr_id = _insert_quarantine_record(db_conn, "cap-aud")
        _insert_capability(db_conn, "cap-aud", safety_lane="quarantine",
                           lifecycle_state="quarantined")
        client.patch(self.url("cap-aud"),
                     json={"action": "hold", "reason": "audit test"}, headers=_auth())
        row = db_conn.fetchone(
            "SELECT detail FROM audit_log WHERE event_type = 'intake_operator_disposition_changed' ORDER BY id DESC LIMIT 1"
        )
        assert row is not None
        detail = json.loads(row["detail"])
        assert detail["action"] == "hold"
        assert detail["intake_capability_id"] == "cap-aud"
        assert detail["before"]["safety_lane"] == "quarantine"
        assert detail["after"]["safety_lane"] == "hold"
        assert detail["after"]["canon_eligible"] is False

    def test_audit_event_includes_quarantine_record_id(self, intake_client):
        client, db_conn, _ = intake_client
        qr_id = _insert_quarantine_record(db_conn, "cap-qrid")
        _insert_capability(db_conn, "cap-qrid", safety_lane="quarantine",
                           lifecycle_state="quarantined")
        client.patch(self.url("cap-qrid"),
                     json={"action": "hold", "reason": "test"}, headers=_auth())
        row = db_conn.fetchone(
            "SELECT detail FROM audit_log WHERE event_type = 'intake_operator_disposition_changed' ORDER BY id DESC LIMIT 1"
        )
        detail = json.loads(row["detail"])
        assert detail["quarantine_record_id"] == qr_id

    def test_client_actor_id_field_is_ignored(self, intake_client):
        """actor_id is server-set; a client-provided value should not appear in the audit."""
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-actorid", safety_lane="quarantine",
                           lifecycle_state="quarantined")
        # Send a spoofed actor_id; the server should ignore it
        r = client.patch(self.url("cap-actorid"),
                         json={"action": "hold", "reason": "test", "actor_id": "evil_actor"},
                         headers=_auth())
        assert r.status_code == 200  # extra fields are silently ignored by Pydantic
        row = db_conn.fetchone(
            "SELECT detail FROM audit_log WHERE event_type = 'intake_operator_disposition_changed' ORDER BY id DESC LIMIT 1"
        )
        detail = json.loads(row["detail"])
        # actor_id in the audit row must be server-set, not client-provided
        audit_row = db_conn.fetchone(
            "SELECT actor_id FROM audit_log WHERE event_type = 'intake_operator_disposition_changed' ORDER BY id DESC LIMIT 1"
        )
        assert audit_row["actor_id"] == "local_operator"

    def test_hold_from_invalid_source_lane_returns_422(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-invlane", safety_lane="ignore",
                           lifecycle_state="quarantined")
        r = client.patch(self.url("cap-invlane"),
                         json={"action": "hold", "reason": "test"}, headers=_auth())
        assert r.status_code == 422

    def test_existing_run_endpoint_unaffected(self, intake_client):
        client, _, _ = intake_client
        r = client.post("/api/intake/run", json={"source_ref": "/x", "batch_id": "b"})
        assert r.status_code == 401  # no token → still 401

    def test_existing_capabilities_get_unaffected(self, intake_client):
        client, _, _ = intake_client
        r = client.get("/api/intake/capabilities")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# TestQuarantineListFiltering (Model A)
# ---------------------------------------------------------------------------

class TestQuarantineListFiltering:
    def test_quarantine_get_excludes_released_items(self, intake_client):
        client, db_conn, _ = intake_client
        # Quarantined cap
        _insert_capability(db_conn, "cap-q1", safety_lane="quarantine")
        _insert_quarantine_record(db_conn, "cap-q1")
        # Released cap — should not appear
        _insert_capability(db_conn, "cap-q2", safety_lane="accept")
        _insert_quarantine_record(db_conn, "cap-q2")

        r = client.get("/api/intake/quarantine")
        assert r.status_code == 200
        items = r.json()["items"]
        cap_ids = [i["intake_capability_id"] for i in items]
        assert "cap-q1" in cap_ids
        assert "cap-q2" not in cap_ids

    def test_quarantine_get_includes_held_items(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-held", safety_lane="hold")
        _insert_quarantine_record(db_conn, "cap-held")
        r = client.get("/api/intake/quarantine")
        cap_ids = [i["intake_capability_id"] for i in r.json()["items"]]
        assert "cap-held" in cap_ids

    def test_quarantine_get_response_includes_current_safety_lane(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-lane", safety_lane="quarantine")
        _insert_quarantine_record(db_conn, "cap-lane")
        items = client.get("/api/intake/quarantine").json()["items"]
        assert any("current_safety_lane" in i for i in items)

    def test_quarantine_get_response_includes_lifecycle_state(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-lc", safety_lane="quarantine",
                           lifecycle_state="quarantined")
        _insert_quarantine_record(db_conn, "cap-lc")
        items = client.get("/api/intake/quarantine").json()["items"]
        assert any(i.get("lifecycle_state") == "quarantined" for i in items)


def test_status_route_includes_intake_scheduler(intake_client):
    """WO-1.1 Phase B item 3: /api/status exposes the managed scheduler status block (read-only)."""
    client, _, _ = intake_client
    r = client.get("/api/status")
    assert r.status_code == 200
    s = r.json().get("intake_scheduler")
    assert s is not None
    for k in ("running", "enabled", "state", "generation", "queued_or_running", "active_workers",
              "drained", "watch_path", "data_root_configured", "last_scan_ts", "last_error",
              "restart_refusal_reason"):
        assert k in s, f"missing intake_scheduler field: {k}"


def test_status_route_scheduler_failure_is_error_block_not_disabled(intake_client, monkeypatch):
    """WO-1.1 closure: a scheduler-status exception renders an explicit error block, not 'disabled'."""
    import app.services.intake.scheduler_manager as sm

    def boom():
        raise RuntimeError("status surface broken")
    monkeypatch.setattr(sm, "status", boom)
    client, _, _ = intake_client
    r = client.get("/api/status")
    assert r.status_code == 200
    s = r.json()["intake_scheduler"]
    assert s["state"] == "error" and s["running"] is False
    assert s["last_error"].startswith("scheduler_status_unavailable:")

    def test_release_then_reload_removes_from_list(self, intake_client):
        client, db_conn, _ = intake_client
        _insert_capability(db_conn, "cap-rl", safety_lane="quarantine",
                           lifecycle_state="quarantined")
        _insert_quarantine_record(db_conn, "cap-rl")
        # Verify visible before release
        before = client.get("/api/intake/quarantine").json()["items"]
        assert any(i["intake_capability_id"] == "cap-rl" for i in before)
        # Release
        r = client.patch(
            "/api/intake/capabilities/cap-rl/operator-disposition",
            json={"action": "release", "reason": "cleared"}, headers=_auth())
        assert r.status_code == 200
        # Verify absent after release
        after = client.get("/api/intake/quarantine").json()["items"]
        assert not any(i["intake_capability_id"] == "cap-rl" for i in after)

    def test_quarantine_empty_still_returns_200(self, intake_client):
        client, _, _ = intake_client
        r = client.get("/api/intake/quarantine")
        assert r.status_code == 200
        assert r.json()["items"] == []

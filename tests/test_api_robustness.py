"""tests/test_api_robustness.py — hardening fixes from the 2026-06-03 test campaign.

A1: numeric query params too large for SQLite (>2^63-1) returned a bare 500; a global
    OverflowError handler now maps them to 422.
A2: a negative limit/offset (?limit=-1) was accepted (200) and silently bypassed the cap;
    list endpoints now declare Query(ge=1)/Query(ge=0) so it is rejected (422). No upper
    bound was added, so A1's max-int boundary behaviour is unchanged.
A3: POST /api/llm/queue/{id}/{approve,reject} for a missing item returned 422; now 404.
A4: GET /api/fold/cluster/{axis}/{value}/trace now validates the axis (400) like its sibling.
"""

from __future__ import annotations

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
    import app.core.auth as auth
    import app.api.main as main
    importlib.reload(auth)
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client


_AUTH = {"X-BOH-Operator-Token": "test-token"}
_OVERFLOW = 9223372036854775808  # 2^63 — one past SQLite's signed-64-bit max


class TestOverflowHandling:
    def test_llm_queue_overflow_is_422_not_500(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            r = c.get(f"/api/llm/queue?limit={_OVERFLOW}")
            assert r.status_code == 422, f"expected 422, got {r.status_code}"

    def test_intake_capabilities_overflow_is_422(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            assert c.get(f"/api/intake/capabilities?limit={_OVERFLOW}").status_code == 422
            assert c.get(f"/api/intake/capabilities?offset={_OVERFLOW}").status_code == 422

    def test_authority_log_overflow_is_422(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            assert c.get(f"/api/authority/log?limit={_OVERFLOW}").status_code == 422

    def test_boundary_max_int_still_ok(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            # 2^63-1 is representable → normal 200.
            assert c.get("/api/llm/queue?limit=9223372036854775807").status_code == 200


# A2: every list endpoint flagged in the campaign now rejects a negative limit.
# These GETs are read-only (no operator token required). doc-scoped paths use an
# arbitrary id — validation runs before any lookup, so a missing doc is irrelevant.
_NEG_LIMIT_PATHS = [
    "/api/llm/queue?limit=-1",
    "/api/intake/capabilities?limit=-1",
    "/api/intake/quarantine?limit=-1",
    "/api/authority/log?limit=-1",
    "/api/authority/promotions?limit=-1",
    "/api/escalation/events?limit=-1",
    "/api/governance/approve/pending?limit=-1",
    "/api/governance/approve/ledger?limit=-1",
    "/api/exec/runs/some-doc?limit=-1",
    "/api/lifecycle/some-doc/history?limit=-1",
    "/api/fold/library?limit=-1",
]


class TestNegativeLimitRejected:
    def test_negative_limit_is_422(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            for path in _NEG_LIMIT_PATHS:
                r = c.get(path)
                assert r.status_code == 422, f"{path} → {r.status_code} (expected 422)"

    def test_negative_offset_is_422(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            assert c.get("/api/intake/capabilities?offset=-1").status_code == 422
            assert c.get("/api/intake/quarantine?offset=-1").status_code == 422

    def test_valid_limit_still_ok(self, tmp_path, monkeypatch):
        # the lower bound rejects negatives without disturbing valid requests
        with _client(tmp_path, monkeypatch) as c:
            assert c.get("/api/llm/queue?limit=1").status_code == 200
            assert c.get("/api/intake/capabilities?limit=1&offset=0").status_code == 200


class TestLlmQueueNotFound:
    def test_approve_missing_item_is_404(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            r = c.post("/api/llm/queue/does-not-exist/approve",
                       json={"actor": "local_operator"}, headers=_AUTH)
            assert r.status_code == 404, f"expected 404, got {r.status_code}"

    def test_reject_missing_item_is_404(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            r = c.post("/api/llm/queue/does-not-exist/reject",
                       json={"actor": "local_operator", "reason": "x"}, headers=_AUTH)
            assert r.status_code == 404


class TestClusterTraceAxisValidation:
    def test_bad_axis_trace_is_400(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            assert c.get("/api/fold/cluster/badaxis/x/trace").status_code == 400

    def test_valid_axis_trace_is_200(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as c:
            r = c.get("/api/fold/cluster/project/anything/trace")
            assert r.status_code == 200
            assert r.json()["available"] is False

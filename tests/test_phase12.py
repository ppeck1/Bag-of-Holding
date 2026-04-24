"""tests/test_phase12.py: Test suite for BOH v2 Phase 12 patch.

Covers:
  - Lifecycle history recording
  - Lifecycle backward movement
  - Lifecycle undo
  - Auto-index scan + hash skipping
  - LLM queue enqueue / approve / reject
  - /api/status endpoint
  - /api/lifecycle/* endpoints
  - /api/llm/queue/* endpoints
  - /api/autoindex/* endpoints

Run: pytest tests/test_phase12.py -v
"""

import os
import time
import tempfile
from pathlib import Path

import pytest

# ── Test DB isolation ─────────────────────────────────────────────────────────
TEST_DB = "boh_test_p12.db"

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_p12.db")
    monkeypatch.setenv("BOH_DB", db_path)
    from app.db import connection as db
    db.init_db()
    yield db
    # cleanup handled by tmp_path


@pytest.fixture()
def client(isolated_db):
    from fastapi.testclient import TestClient
    from app.api.main import app
    return TestClient(app)


@pytest.fixture()
def sample_doc(isolated_db):
    """Insert a minimal doc record and return its doc_id."""
    import uuid
    doc_id = str(uuid.uuid4())
    isolated_db.execute(
        """INSERT INTO docs
           (doc_id, path, type, status, operator_state, operator_intent,
            topics_tokens, corpus_class, updated_ts)
           VALUES (?, ?, 'note', 'draft', 'observe', 'capture', 'test', 'CORPUS_CLASS:DRAFT', ?)""",
        (doc_id, f"/tmp/test_{doc_id[:8]}.md", int(time.time())),
    )
    return doc_id


# ── Lifecycle history ─────────────────────────────────────────────────────────

class TestLifecycleHistory:
    def test_record_event(self, sample_doc):
        from app.core.lifecycle import record_event, get_history
        eid = record_event(sample_doc, "observe", "vessel", actor="test", direction="forward")
        assert isinstance(eid, int) and eid > 0
        history = get_history(sample_doc)
        assert len(history) == 1
        assert history[0]["from_state"] == "observe"
        assert history[0]["to_state"] == "vessel"

    def test_history_is_append_only(self, sample_doc):
        from app.core.lifecycle import record_event, get_history
        record_event(sample_doc, "observe", "vessel")
        record_event(sample_doc, "vessel", "constraint")
        history = get_history(sample_doc)
        assert len(history) == 2

    def test_no_history_returns_empty(self, sample_doc):
        from app.core.lifecycle import get_history
        assert get_history(sample_doc) == []


# ── Lifecycle backward ────────────────────────────────────────────────────────

class TestLifecycleBackward:
    def _advance_to(self, db, doc_id, target_state):
        db.execute(
            "UPDATE docs SET operator_state = ? WHERE doc_id = ?", (target_state, doc_id)
        )

    def test_backward_from_vessel(self, isolated_db, sample_doc):
        from app.core.lifecycle import move_backward
        self._advance_to(isolated_db, sample_doc, "vessel")
        result = move_backward(sample_doc, reason="test rollback")
        assert result["success"] is True
        assert result["new_state"] == "observe"
        assert result["previous_state"] == "vessel"

    def test_backward_from_release(self, isolated_db, sample_doc):
        from app.core.lifecycle import move_backward
        self._advance_to(isolated_db, sample_doc, "release")
        result = move_backward(sample_doc)
        assert result["success"] is True
        assert result["new_state"] == "integrate"

    def test_backward_from_observe_fails(self, sample_doc):
        from app.core.lifecycle import move_backward
        # observe is initial state — no backward possible
        result = move_backward(sample_doc)
        assert result["success"] is False
        assert "initial state" in result["error"]

    def test_backward_records_history(self, isolated_db, sample_doc):
        from app.core.lifecycle import move_backward, get_history
        self._advance_to(isolated_db, sample_doc, "integrate")
        move_backward(sample_doc, reason="test")
        history = get_history(sample_doc)
        assert any(h["direction"] == "backward" for h in history)

    def test_backward_does_not_erase_prior_history(self, isolated_db, sample_doc):
        from app.core.lifecycle import record_event, move_backward, get_history
        record_event(sample_doc, "observe", "vessel", direction="forward")
        self._advance_to(isolated_db, sample_doc, "vessel")
        move_backward(sample_doc)
        history = get_history(sample_doc)
        assert len(history) == 2   # original + backward


# ── Lifecycle undo ────────────────────────────────────────────────────────────

class TestLifecycleUndo:
    def test_undo_last_reverts_state(self, isolated_db, sample_doc):
        from app.core.lifecycle import record_event, undo_last
        # Manually advance and record
        isolated_db.execute(
            "UPDATE docs SET operator_state = 'vessel' WHERE doc_id = ?", (sample_doc,)
        )
        record_event(sample_doc, "observe", "vessel")
        result = undo_last(sample_doc)
        assert result["success"] is True
        assert result["new_state"] == "observe"

    def test_undo_with_no_history_fails(self, sample_doc):
        from app.core.lifecycle import undo_last
        result = undo_last(sample_doc)
        assert result["success"] is False
        assert "No lifecycle history" in result["error"]

    def test_undo_appends_history_record(self, isolated_db, sample_doc):
        from app.core.lifecycle import record_event, undo_last, get_history
        isolated_db.execute(
            "UPDATE docs SET operator_state = 'vessel' WHERE doc_id = ?", (sample_doc,)
        )
        record_event(sample_doc, "observe", "vessel")
        undo_last(sample_doc)
        history = get_history(sample_doc)
        assert len(history) == 2
        assert history[0]["direction"] == "undo"


# ── Auto-index ────────────────────────────────────────────────────────────────

class TestAutoIndex:
    def test_scan_library_finds_markdown(self, tmp_path):
        from app.core.autoindex import scan_library
        (tmp_path / "a.md").write_text("# Hello")
        (tmp_path / "b.txt").write_text("plain text")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.md").write_text("# Sub")
        paths = scan_library(str(tmp_path))
        assert any("a.md" in p for p in paths)
        assert any("c.md" in p for p in paths)

    def test_scan_empty_library(self, tmp_path):
        from app.core.autoindex import scan_library
        paths = scan_library(str(tmp_path))
        assert paths == []

    def test_scan_missing_library(self):
        from app.core.autoindex import scan_library
        paths = scan_library("/nonexistent/path/xyz")
        assert paths == []

    def test_get_status_returns_dict(self):
        from app.core.autoindex import get_status
        st = get_status()
        assert isinstance(st, dict)
        assert "last_run_ts" in st

    def test_run_auto_index_empty_library(self, tmp_path):
        from app.core.autoindex import run_auto_index
        result = run_auto_index(library_root=str(tmp_path))
        assert result["scanned"] == 0
        assert result["indexed"] == 0
        assert result["failed"] == 0


# ── LLM Queue ─────────────────────────────────────────────────────────────────

class TestLlmQueue:
    SAMPLE_PROPOSAL = {
        "proposed_title": "Test Document",
        "summary": "A test summary.",
        "proposed_topics": ["test", "phase12"],
        "proposed_type": "note",
        "proposed_status": "draft",
        "confidence": 0.75,
    }

    def test_enqueue_returns_queue_id(self):
        from app.core.llm_queue import enqueue
        qid = enqueue(self.SAMPLE_PROPOSAL, doc_id="test-doc")
        assert isinstance(qid, str) and len(qid) == 36  # UUID

    def test_get_queue_returns_pending(self):
        from app.core.llm_queue import enqueue, get_queue
        enqueue(self.SAMPLE_PROPOSAL)
        items = get_queue(status="pending")
        assert len(items) >= 1
        assert items[0]["proposed"]["proposed_title"] == "Test Document"

    def test_get_pending_count(self):
        from app.core.llm_queue import enqueue, get_pending_count
        before = get_pending_count()
        enqueue(self.SAMPLE_PROPOSAL)
        assert get_pending_count() == before + 1

    def test_approve_applies_safe_fields(self, isolated_db, sample_doc):
        from app.core.llm_queue import enqueue, approve, get_queue
        qid = enqueue(self.SAMPLE_PROPOSAL, doc_id=sample_doc)
        result = approve(qid)
        assert result["success"] is True
        assert "title" in result["applied"] or "summary" in result["applied"]
        # Doc title should be updated
        doc = isolated_db.fetchone("SELECT title FROM docs WHERE doc_id = ?", (sample_doc,))
        assert doc["title"] == "Test Document"

    def test_approve_never_makes_canonical(self, sample_doc):
        """Approving a proposal with proposed_status=canonical must NOT set status=canonical."""
        from app.core.llm_queue import enqueue, approve
        evil_proposal = {**self.SAMPLE_PROPOSAL, "proposed_status": "canonical", "proposed_type": "canon"}
        qid = enqueue(evil_proposal, doc_id=sample_doc)
        result = approve(qid)
        assert result["success"] is True
        # type=canon must NOT be applied
        assert "type" not in result["applied"]

    def test_reject_leaves_doc_unchanged(self, isolated_db, sample_doc):
        from app.core.llm_queue import enqueue, reject
        original = isolated_db.fetchone("SELECT title FROM docs WHERE doc_id = ?", (sample_doc,))
        qid = enqueue(self.SAMPLE_PROPOSAL, doc_id=sample_doc)
        result = reject(qid, reason="not relevant")
        assert result["success"] is True
        after = isolated_db.fetchone("SELECT title FROM docs WHERE doc_id = ?", (sample_doc,))
        assert after["title"] == original["title"]

    def test_reject_pending_to_rejected(self):
        from app.core.llm_queue import enqueue, reject, get_queue
        qid = enqueue(self.SAMPLE_PROPOSAL)
        reject(qid)
        items = get_queue(status="rejected")
        assert any(i["queue_id"] == qid for i in items)

    def test_double_approve_fails(self):
        from app.core.llm_queue import enqueue, approve
        qid = enqueue(self.SAMPLE_PROPOSAL)
        approve(qid)
        result = approve(qid)
        assert result["success"] is False
        assert "already" in result["error"]


# ── API endpoints ─────────────────────────────────────────────────────────────

class TestStatusEndpoint:
    def test_status_ok(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert data["server"] == "ok"
        assert data["phase"] == 12
        assert "indexed_docs" in data
        assert "ollama" in data
        assert "review_queue" in data

    def test_health_phase_12(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["phase"] == 12


class TestLifecycleEndpoints:
    def test_history_empty(self, client, sample_doc):
        r = client.get(f"/api/lifecycle/{sample_doc}/history")
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_can_backward_from_observe(self, client, sample_doc):
        r = client.get(f"/api/lifecycle/{sample_doc}/can-backward")
        assert r.status_code == 200
        data = r.json()
        # observe has no backward
        assert data["possible"] is False

    def test_backward_and_history(self, client, isolated_db, sample_doc):
        isolated_db.execute(
            "UPDATE docs SET operator_state = 'vessel' WHERE doc_id = ?", (sample_doc,)
        )
        r = client.post(
            f"/api/lifecycle/{sample_doc}/backward",
            json={"reason": "API test", "actor": "pytest"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["new_state"] == "observe"

        # History should now have 1 entry
        rh = client.get(f"/api/lifecycle/{sample_doc}/history")
        assert rh.json()["count"] == 1

    def test_undo_no_history_422(self, client, sample_doc):
        r = client.post(f"/api/lifecycle/{sample_doc}/undo", json={"actor": "pytest"})
        assert r.status_code == 422


class TestLlmQueueEndpoints:
    PROPOSAL = {
        "proposed_title": "API Test Doc",
        "summary": "Summary via API.",
        "proposed_topics": ["api", "test"],
        "proposed_type": "note",
        "confidence": 0.8,
    }

    def test_enqueue_via_api(self, client):
        r = client.post("/api/llm/queue", json={"proposed": self.PROPOSAL})
        assert r.status_code == 200
        assert "queue_id" in r.json()

    def test_queue_count(self, client):
        client.post("/api/llm/queue", json={"proposed": self.PROPOSAL})
        r = client.get("/api/llm/queue/count")
        assert r.status_code == 200
        assert r.json()["pending"] >= 1

    def test_approve_via_api(self, client, sample_doc):
        rq = client.post("/api/llm/queue", json={"proposed": self.PROPOSAL, "doc_id": sample_doc})
        qid = rq.json()["queue_id"]
        r = client.post(f"/api/llm/queue/{qid}/approve", json={"actor": "pytest"})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_reject_via_api(self, client):
        rq = client.post("/api/llm/queue", json={"proposed": self.PROPOSAL})
        qid = rq.json()["queue_id"]
        r = client.post(f"/api/llm/queue/{qid}/reject", json={"actor": "pytest", "reason": "Not needed"})
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestAutoIndexEndpoints:
    def test_status_endpoint(self, client):
        r = client.get("/api/autoindex/status")
        assert r.status_code == 200
        assert "last_run_ts" in r.json()

    def test_run_empty_library(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        r = client.post("/api/autoindex/run", json={"changed_only": False})
        assert r.status_code == 200
        data = r.json()
        assert data["scanned"] == 0
        assert data["indexed"] == 0

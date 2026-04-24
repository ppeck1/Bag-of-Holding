"""tests/test_ollama_hardening.py: Phase 12.H Ollama hardening tests.

Covers all 8 required behaviours:
  1. invoke blocked (503) when BOH_OLLAMA_ENABLED != "true"
  2. timeout clamped to [1, 120]; out-of-range values rejected by Pydantic
  3. content > 20,000 chars rejected with 422
  4. empty / root / wildcard scope dirs rejected with 422
  5. malformed fenced JSON parsed correctly (regex stripping)
  6. successful mocked Ollama JSON response handled correctly
  7. no direct write / canon mutation from Ollama output
  8. health and model listing accessible even when disabled

All tests use DB isolation and monkeypatching — no real Ollama required.
"""

import json
import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient


# ── DB isolation fixture ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BOH_DB", str(tmp_path / "test_hardening.db"))
    from app.db import connection as db
    db.init_db()
    yield db


@pytest.fixture()
def client(isolated_db):
    from app.api.main import app
    return TestClient(app, raise_server_exceptions=True)


# ── Helper: insert a minimal doc ─────────────────────────────────────────────

@pytest.fixture()
def sample_doc_id(isolated_db):
    doc_id = f"test-{uuid.uuid4().hex[:8]}"
    isolated_db.execute(
        """INSERT INTO docs
           (doc_id, path, type, status, operator_state, operator_intent,
            topics_tokens, corpus_class, updated_ts)
           VALUES (?, '/tmp/test.md', 'note', 'draft',
                   'observe', 'capture', 'test', 'CORPUS_CLASS:DRAFT', ?)""",
        (doc_id, int(time.time())),
    )
    return doc_id


# ── 1. invoke blocked when disabled ──────────────────────────────────────────

class TestInvokeGating:
    def test_invoke_blocked_when_disabled(self, client, monkeypatch):
        """POST /api/ollama/invoke returns 503 when BOH_OLLAMA_ENABLED is not set."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "false")
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "Hello world",
        })
        assert r.status_code == 503
        assert "disabled" in r.json()["detail"].lower()

    def test_invoke_blocked_when_env_absent(self, client, monkeypatch):
        """Default (no env var) must also return 503."""
        monkeypatch.delenv("BOH_OLLAMA_ENABLED", raising=False)
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "Hello world",
        })
        assert r.status_code == 503

    def test_invoke_allowed_when_enabled_with_mock(self, client, monkeypatch):
        """With BOH_OLLAMA_ENABLED=true and a mocked Ollama, invoke returns 200."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(ol_mod, "_call_ollama",
                            lambda *a, **k: ('{"summary": "mocked"}', None))
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "Short content",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["non_authoritative"] is True

    def test_health_accessible_when_disabled(self, client, monkeypatch):
        """GET /api/ollama/health is always accessible regardless of enabled flag."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "false")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(ol_mod, "health_check",
                            lambda: {"available": False, "models": [], "url": "mock"})
        r = client.get("/api/ollama/health")
        assert r.status_code == 200

    def test_models_accessible_when_disabled(self, client, monkeypatch):
        """GET /api/ollama/models is always accessible."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "false")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(ol_mod, "list_models", lambda: [])
        r = client.get("/api/ollama/models")
        assert r.status_code == 200


# ── 2. Timeout cap ───────────────────────────────────────────────────────────

class TestTimeoutCap:
    def test_timeout_above_120_rejected(self, client, monkeypatch):
        """timeout > 120 is rejected by Pydantic validation (422)."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test",
            "timeout":   9999,
        })
        assert r.status_code == 422

    def test_timeout_zero_rejected(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test",
            "timeout":   0,
        })
        assert r.status_code == 422

    def test_timeout_negative_rejected(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test",
            "timeout":   -5,
        })
        assert r.status_code == 422

    def test_timeout_120_accepted(self, client, monkeypatch):
        """Boundary value 120 is accepted."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(ol_mod, "_call_ollama",
                            lambda *a, **k: ('{"summary": "ok"}', None))
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test",
            "timeout":   120,
        })
        assert r.status_code == 200

    def test_timeout_1_accepted(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(ol_mod, "_call_ollama",
                            lambda *a, **k: ('{"summary": "ok"}', None))
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test",
            "timeout":   1,
        })
        assert r.status_code == 200

    def test_core_clamps_timeout(self, monkeypatch):
        """Core invoke() clamps timeout even without route layer."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        calls: list = []
        def capture(model, sys_p, content, timeout, use_json_mode):
            calls.append(timeout)
            return ('{"summary": "clamped"}', None)
        monkeypatch.setattr(ol_mod, "_call_ollama", capture)
        ol_mod.invoke("summarize_doc", "test", timeout=9999)
        assert calls and calls[0] == ol_mod._TIMEOUT_MAX


# ── 3. Content size rejection ─────────────────────────────────────────────────

class TestContentSizeCap:
    def test_content_over_limit_rejected_at_route(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "x" * 20_001,
        })
        assert r.status_code == 422
        assert "too large" in r.json()["detail"].lower()

    def test_content_at_limit_accepted(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(ol_mod, "_call_ollama",
                            lambda *a, **k: ('{"summary": "ok"}', None))
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "x" * 20_000,
        })
        assert r.status_code == 200

    def test_core_rejects_oversized_content(self, monkeypatch):
        """Core enforce independently of route layer."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        result = ol_mod.invoke("summarize_doc", "z" * 20_001)
        assert result.get("content_too_large") is True
        assert "error" in result


# ── 4. Empty / root scope dir rejection ──────────────────────────────────────

class TestScopeDirValidation:
    @pytest.mark.parametrize("bad_dir", [
        "", ".", "/", "*", "/*", "./", "**",
    ])
    def test_bad_scope_dirs_rejected(self, bad_dir, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        from app.core.ollama import _validate_scope_dirs
        safe, rejected = _validate_scope_dirs([bad_dir])
        assert not safe
        assert bad_dir in rejected

    def test_absolute_path_rejected(self, monkeypatch):
        from app.core.ollama import _validate_scope_dirs
        safe, rejected = _validate_scope_dirs(["/etc/passwd"])
        assert not safe
        assert rejected

    def test_valid_relative_dir_accepted(self, monkeypatch):
        from app.core.ollama import _validate_scope_dirs
        safe, rejected = _validate_scope_dirs(["library/docs", "notes/2026"])
        assert set(safe) == {"library/docs", "notes/2026"}
        assert not rejected

    def test_route_rejects_empty_dir_scope(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test content",
            "scope":     {"dirs": [""]},
        })
        assert r.status_code == 422
        assert "rejected" in r.json()["detail"].lower()

    def test_route_rejects_root_dir_scope(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test content",
            "scope":     {"dirs": ["/"]},
        })
        assert r.status_code == 422

    def test_mixed_dirs_all_rejected_if_any_bad(self, client, monkeypatch):
        """If any dir is rejected, entire request is rejected."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test",
            "scope":     {"dirs": ["good/dir", ""]},
        })
        assert r.status_code == 422


# ── 5. JSON fence parsing ─────────────────────────────────────────────────────

class TestJsonFenceParsing:
    def test_plain_json_parsed(self):
        from app.core.ollama import _strip_json_fences
        assert _strip_json_fences('{"key": "val"}') == '{"key": "val"}'

    def test_json_fence_stripped(self):
        from app.core.ollama import _strip_json_fences
        raw = '```json\n{"key": "val"}\n```'
        assert _strip_json_fences(raw) == '{"key": "val"}'

    def test_plain_fence_stripped(self):
        from app.core.ollama import _strip_json_fences
        raw = '```\n{"key": "val"}\n```'
        assert _strip_json_fences(raw) == '{"key": "val"}'

    def test_fence_with_extra_whitespace(self):
        from app.core.ollama import _strip_json_fences
        raw = '  ```json  \n  {"a": 1}  \n  ```  '
        result = _strip_json_fences(raw)
        assert json.loads(result) == {"a": 1}

    def test_no_fence_passthrough(self):
        from app.core.ollama import _strip_json_fences
        raw = '{"no": "fence"}'
        assert _strip_json_fences(raw) == raw

    def test_lstrip_bug_not_present(self):
        """Confirm that the old lstrip('```json') bug is gone.

        lstrip treats its argument as a set of chars, so it would strip
        'j', 's', 'o', 'n', '`' individually, corrupting values like
        '{"json_key": 1}' → '{_key": 1}'.
        The new regex approach must not corrupt the value.
        """
        from app.core.ollama import _strip_json_fences
        # This would have been corrupted by the old lstrip approach
        raw = '```json\n{"json_flag": true, "nonce": 42}\n```'
        result = _strip_json_fences(raw)
        parsed = json.loads(result)
        assert parsed["json_flag"] is True
        assert parsed["nonce"] == 42

    def test_nested_json_string_preserved(self):
        """Values containing backticks or 'json' are not corrupted."""
        from app.core.ollama import _strip_json_fences
        raw = '```json\n{"code": "x = `hello`", "lang": "json"}\n```'
        result = _strip_json_fences(raw)
        parsed = json.loads(result)
        assert parsed["code"] == "x = `hello`"
        assert parsed["lang"] == "json"


# ── 6. Successful mocked Ollama JSON response ─────────────────────────────────

class TestMockedOllamaResponse:
    def test_successful_summarize_with_mock(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(
            ol_mod, "_call_ollama",
            lambda *a, **k: ('{"summary": "Document covers planar math and lifecycle."}', None)
        )
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "Some document content here.",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["non_authoritative"] is True
        assert data["requires_explicit_confirmation"] is True
        assert data["response_json"]["summary"] == "Document covers planar math and lifecycle."

    def test_fenced_json_response_parsed(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(
            ol_mod, "_call_ollama",
            lambda *a, **k: ('```json\n{"issues": [], "quality_score": 0.9}\n```', None)
        )
        r = client.post("/api/ollama/invoke", json={
            "task_type": "review_doc",
            "content":   "doc content",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["response_json"]["quality_score"] == pytest.approx(0.9)

    def test_ollama_error_recorded_in_invocation(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(
            ol_mod, "_call_ollama",
            lambda *a, **k: ("", "Connection refused")
        )
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert data["error"] == "Connection refused"
        assert data["non_authoritative"] is True

    def test_json_mode_flag_passed_for_structured_tasks(self, monkeypatch):
        """_call_ollama receives use_json_mode=True for JSON-output tasks."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        received: list = []
        def capture(model, sys_p, content, timeout, use_json_mode):
            received.append(use_json_mode)
            return ('{"summary": "ok"}', None)
        monkeypatch.setattr(ol_mod, "_call_ollama", capture)
        ol_mod.invoke("summarize_doc", "test content")
        assert received == [True]

    def test_generate_code_not_json_mode(self, monkeypatch):
        """generate_code is not in _JSON_TASKS — should not get json mode."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        received: list = []
        def capture(model, sys_p, content, timeout, use_json_mode):
            received.append(use_json_mode)
            return ('{"code": "print(1)", "language": "python", "description": ""}', None)
        monkeypatch.setattr(ol_mod, "_call_ollama", capture)
        ol_mod.invoke("generate_code", "write hello world")
        assert received == [False]


# ── 7. No direct write / canon mutation from Ollama output ───────────────────

class TestNoCanonMutation:
    def test_invoke_does_not_write_to_docs_table(
        self, client, monkeypatch, sample_doc_id, isolated_db
    ):
        """Approving an Ollama response must not change docs.status to 'canonical'."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(
            ol_mod, "_call_ollama",
            lambda *a, **k: (
                json.dumps({
                    "proposed_patch": {
                        "status": "canonical",
                        "operator_state": "release",
                    },
                    "reasoning": "This should be canon",
                }),
                None,
            )
        )
        # Invoke propose_metadata_patch
        r = client.post("/api/ollama/invoke", json={
            "task_type": "propose_metadata_patch",
            "content":   "Proposal to canonize",
            "doc_id":    sample_doc_id,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["non_authoritative"] is True
        assert data["requires_explicit_confirmation"] is True

        # The doc must NOT have been mutated — status remains 'draft'
        doc = isolated_db.fetchone(
            "SELECT status, operator_state FROM docs WHERE doc_id = ?",
            (sample_doc_id,),
        )
        assert doc["status"] == "draft"
        assert doc["operator_state"] == "observe"

    def test_invoke_result_has_no_write_side_effect(
        self, client, monkeypatch, isolated_db
    ):
        """invoke() itself never executes SQL UPDATE on docs table."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(
            ol_mod, "_call_ollama",
            lambda *a, **k: ('{"summary": "no side effects"}', None)
        )
        before = isolated_db.fetchone("SELECT COUNT(*) AS n FROM docs")["n"]
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test",
        })
        assert r.status_code == 200
        after = isolated_db.fetchone("SELECT COUNT(*) AS n FROM docs")["n"]
        # Row count unchanged
        assert before == after

    def test_non_authoritative_always_true(self, client, monkeypatch):
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(
            ol_mod, "_call_ollama",
            lambda *a, **k: ('{"summary": "test"}', None)
        )
        r = client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "test",
        })
        data = r.json()
        assert data.get("non_authoritative") is True
        assert data.get("requires_explicit_confirmation") is True

    def test_invocation_recorded_in_audit(self, client, monkeypatch, isolated_db):
        """Every invoke call appends an audit_log entry."""
        monkeypatch.setenv("BOH_OLLAMA_ENABLED", "true")
        import app.core.ollama as ol_mod
        monkeypatch.setattr(
            ol_mod, "_call_ollama",
            lambda *a, **k: ('{"summary": "audited"}', None)
        )
        before = isolated_db.fetchone(
            "SELECT COUNT(*) AS n FROM audit_log WHERE event_type = 'llm_call'"
        )["n"]
        client.post("/api/ollama/invoke", json={
            "task_type": "summarize_doc",
            "content":   "audit me",
        })
        after = isolated_db.fetchone(
            "SELECT COUNT(*) AS n FROM audit_log WHERE event_type = 'llm_call'"
        )["n"]
        assert after == before + 1

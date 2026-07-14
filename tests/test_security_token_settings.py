import asyncio
import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest


OPERATOR_ONE = "operator-token-one-1234"
OPERATOR_TWO = "operator-token-two-5678"
RETRIEVAL_ONE = "retrieval-token-one-1234"


def _app(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir(exist_ok=True)
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.delenv("BOH_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("BOH_RETRIEVAL_TOKEN", raising=False)

    import app.db.connection as db

    db.DB_PATH = str(db_path)
    db.init_db()

    import app.core.token_config as token_config
    import app.core.auth as auth
    import app.core.retrieval as retrieval
    import app.api.routes.security_settings_routes as security_routes
    import app.api.main as main

    importlib.reload(token_config)
    importlib.reload(auth)
    importlib.reload(retrieval)
    importlib.reload(security_routes)
    importlib.reload(main)
    return main.app, db, token_config


def _request(
    app,
    method,
    path,
    *,
    client_host="127.0.0.1",
    base_url="http://127.0.0.1",
    **kwargs,
):
    async def run():
        transport = httpx.ASGITransport(app=app, client=(client_host, 12345))
        async with httpx.AsyncClient(
            transport=transport, base_url=base_url
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def _operator_headers(value=OPERATOR_ONE, *, origin=True):
    headers = {"X-BOH-Operator-Token": value}
    if origin:
        headers["Origin"] = "http://127.0.0.1"
    return headers


def test_loopback_bootstrap_persists_only_hash_and_audits_safely(tmp_path, monkeypatch):
    app, db, _token_config = _app(tmp_path, monkeypatch)

    response = _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": OPERATOR_ONE},
        headers={"Origin": "http://127.0.0.1"},
    )
    assert response.status_code == 200
    assert response.json()["token"]["source"] == "ui"
    assert response.json()["plaintext_persisted"] is False
    assert OPERATOR_ONE not in response.text

    stored = db.fetchone(
        "SELECT value FROM system_config WHERE key='security_operator_token_v1'"
    )["value"]
    record = json.loads(stored)
    assert record["algorithm"] == "pbkdf2_sha256"
    assert OPERATOR_ONE not in stored

    audit = db.fetchone(
        "SELECT detail FROM audit_log WHERE event_type='security_token_configured' "
        "ORDER BY id DESC LIMIT 1"
    )["detail"]
    assert OPERATOR_ONE not in audit
    assert "digest" not in audit and "salt" not in audit
    assert json.loads(audit)["plaintext_persisted"] is False

    assert _request(app, "POST", "/api/operator/check").status_code == 401
    assert _request(
        app, "POST", "/api/operator/check", headers=_operator_headers("wrong-token-value")
    ).status_code == 403
    assert _request(
        app, "POST", "/api/operator/check", headers=_operator_headers()
    ).status_code == 200


def test_rotation_requires_current_token_and_survives_reload(tmp_path, monkeypatch):
    app, db, token_config = _app(tmp_path, monkeypatch)
    assert _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": OPERATOR_ONE},
        headers={"Origin": "http://127.0.0.1"},
    ).status_code == 200
    first_record = db.fetchone(
        "SELECT value FROM system_config WHERE key='security_operator_token_v1'"
    )["value"]

    missing = _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": OPERATOR_TWO},
        headers={"Origin": "http://127.0.0.1"},
    )
    wrong = _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": OPERATOR_TWO},
        headers=_operator_headers("not-the-current-token"),
    )
    assert missing.status_code == 401
    assert wrong.status_code == 403

    rotated = _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": OPERATOR_TWO},
        headers=_operator_headers(),
    )
    assert rotated.status_code == 200
    second_record = db.fetchone(
        "SELECT value FROM system_config WHERE key='security_operator_token_v1'"
    )["value"]
    assert first_record != second_record
    assert _request(
        app, "POST", "/api/operator/check", headers=_operator_headers()
    ).status_code == 403

    importlib.reload(token_config)
    assert token_config.verify("operator", OPERATOR_TWO) is True
    assert token_config.verify("operator", OPERATOR_ONE) is False


def test_retrieval_configuration_requires_operator_and_tokens_are_distinct(tmp_path, monkeypatch):
    app, _db, _token_config = _app(tmp_path, monkeypatch)
    retrieval_path = "/api/security/tokens/retrieval"

    before_operator = _request(
        app,
        "POST",
        retrieval_path,
        json={"token": RETRIEVAL_ONE},
        headers={"Origin": "http://127.0.0.1"},
    )
    assert before_operator.status_code == 409

    assert _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": OPERATOR_ONE},
        headers={"Origin": "http://127.0.0.1"},
    ).status_code == 200
    configured = _request(
        app,
        "POST",
        retrieval_path,
        json={"token": RETRIEVAL_ONE},
        headers=_operator_headers(),
    )
    assert configured.status_code == 200

    missing = _request(app, "POST", "/api/retrieve", json={"query": "context"})
    operator_as_retrieval = _request(
        app,
        "POST",
        "/api/retrieve",
        json={"query": "context"},
        headers={"X-BOH-Retrieval-Token": OPERATOR_ONE},
    )
    retrieval = _request(
        app,
        "POST",
        "/api/retrieve",
        json={"query": "context"},
        headers={"X-BOH-Retrieval-Token": RETRIEVAL_ONE},
    )
    assert missing.status_code == 401
    assert operator_as_retrieval.status_code == 403
    assert retrieval.status_code == 200


def test_sixteen_character_numeric_credentials_work_when_roles_differ(tmp_path, monkeypatch):
    app, _db, _token_config = _app(tmp_path, monkeypatch)
    operator_value = "1234567890123456"
    retrieval_value = "6543210987654321"

    operator = _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": operator_value},
        headers={"Origin": "http://127.0.0.1"},
    )
    assert operator.status_code == 200
    retrieval = _request(
        app,
        "POST",
        "/api/security/tokens/retrieval",
        json={"token": retrieval_value},
        headers=_operator_headers(operator_value),
    )
    assert retrieval.status_code == 200
    assert _request(
        app,
        "POST",
        "/api/retrieve",
        json={"query": "context"},
        headers={"X-BOH-Retrieval-Token": retrieval_value},
    ).status_code == 200


def test_unconfigured_retrieval_is_open_only_to_loopback_development_clients(tmp_path, monkeypatch):
    app, _db, _token_config = _app(tmp_path, monkeypatch)
    local = _request(app, "POST", "/api/retrieve", json={"query": "context"})
    remote = _request(
        app,
        "POST",
        "/api/retrieve",
        client_host="192.0.2.10",
        json={"query": "context"},
    )
    assert local.status_code == 200
    assert remote.status_code == 403


def test_local_origin_boundary_and_environment_precedence(tmp_path, monkeypatch):
    app, db, _token_config = _app(tmp_path, monkeypatch)
    path = "/api/security/tokens/operator"
    payload = {"token": OPERATOR_ONE}

    remote = _request(app, "POST", path, client_host="192.0.2.10", json=payload)
    no_origin = _request(app, "POST", path, json=payload)
    cross_origin = _request(
        app,
        "POST",
        path,
        json=payload,
        headers={"Origin": "http://evil.example"},
    )
    hostile_matching_host = _request(
        app,
        "POST",
        path,
        base_url="http://evil.example",
        json=payload,
        headers={"Origin": "http://evil.example"},
    )
    malformed_origin = _request(
        app,
        "POST",
        path,
        json=payload,
        headers={"Origin": "http://127.0.0.1:99999"},
    )
    assert remote.status_code == 403
    assert no_origin.status_code == 403
    assert cross_origin.status_code == 403
    assert hostile_matching_host.status_code == 403
    assert malformed_origin.status_code == 403
    assert db.fetchone(
        "SELECT value FROM system_config WHERE key='security_operator_token_v1'"
    ) is None

    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "environment-operator-token")
    environment_owned = _request(
        app,
        "POST",
        path,
        json=payload,
        headers={
            "Origin": "http://127.0.0.1",
            "X-BOH-Operator-Token": "environment-operator-token",
        },
    )
    assert environment_owned.status_code == 409
    status = _request(app, "GET", "/api/security/tokens").json()["operator"]
    assert status["source"] == "environment"
    assert status["managed_by_environment"] is True
    assert status["restart_required"] is True


def test_malformed_verifier_fails_closed_and_invalid_input_is_redacted(tmp_path, monkeypatch):
    app, db, _token_config = _app(tmp_path, monkeypatch)
    secret_invalid = "unique invalid secret value"
    invalid = _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": secret_invalid},
        headers={"Origin": "http://127.0.0.1"},
    )
    assert invalid.status_code == 422
    assert secret_invalid not in invalid.text

    db.execute(
        "INSERT INTO system_config (key, value, updated_ts) VALUES (?, ?, 1)",
        ("security_operator_token_v1", "{malformed"),
    )
    state = _request(app, "GET", "/api/operator/status").json()
    assert state["configured"] is True
    assert state["dev_open"] is False
    assert state["record_valid"] is False
    assert _request(app, "POST", "/api/operator/check").status_code == 401
    assert _request(
        app, "POST", "/api/operator/check", headers=_operator_headers()
    ).status_code == 403


def test_unicode_and_cross_role_token_values_are_rejected_without_persistence(tmp_path, monkeypatch):
    app, db, _token_config = _app(tmp_path, monkeypatch)
    unicode_secret = "operator-token-value-😀"
    unicode_response = _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": unicode_secret},
        headers={"Origin": "http://127.0.0.1"},
    )
    assert unicode_response.status_code == 422
    assert unicode_secret not in unicode_response.text
    assert db.fetchone(
        "SELECT value FROM system_config WHERE key='security_operator_token_v1'"
    ) is None

    assert _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": OPERATOR_ONE},
        headers={"Origin": "http://127.0.0.1"},
    ).status_code == 200
    same_role = _request(
        app,
        "POST",
        "/api/security/tokens/retrieval",
        json={"token": OPERATOR_ONE},
        headers=_operator_headers(),
    )
    assert same_role.status_code == 422
    assert _request(
        app,
        "POST",
        "/api/security/tokens/retrieval",
        json={"token": RETRIEVAL_ONE},
        headers=_operator_headers(),
    ).status_code == 200
    collapse_on_rotate = _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": RETRIEVAL_ONE},
        headers=_operator_headers(),
    )
    assert collapse_on_rotate.status_code == 422


def test_clear_requires_authority_is_audited_and_environment_can_retire_dormant_ui(tmp_path, monkeypatch):
    app, db, _token_config = _app(tmp_path, monkeypatch)
    origin = {"Origin": "http://127.0.0.1"}
    assert _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": OPERATOR_ONE},
        headers=origin,
    ).status_code == 200
    assert _request(
        app,
        "POST",
        "/api/security/tokens/retrieval",
        json={"token": RETRIEVAL_ONE},
        headers=_operator_headers(),
    ).status_code == 200

    missing = _request(
        app,
        "DELETE",
        "/api/security/tokens/retrieval",
        headers=origin,
    )
    assert missing.status_code == 401
    cleared_retrieval = _request(
        app,
        "DELETE",
        "/api/security/tokens/retrieval",
        headers=_operator_headers(),
    )
    assert cleared_retrieval.status_code == 200
    assert cleared_retrieval.json()["token"]["configured"] is False

    monkeypatch.setenv("BOH_OPERATOR_TOKEN", OPERATOR_TWO)
    environment_state = _request(app, "GET", "/api/security/tokens").json()["operator"]
    assert environment_state["source"] == "environment"
    assert environment_state["ui_verifier_present"] is True
    retired = _request(
        app,
        "DELETE",
        "/api/security/tokens/operator",
        headers=_operator_headers(OPERATOR_TWO),
    )
    assert retired.status_code == 200
    assert retired.json()["token"]["source"] == "environment"
    assert retired.json()["token"]["ui_verifier_present"] is False
    assert db.fetchone(
        "SELECT value FROM system_config WHERE key='security_operator_token_v1'"
    ) is None

    clears = db.fetchall(
        "SELECT detail FROM audit_log WHERE event_type='security_token_configured' "
        "ORDER BY id"
    )
    clear_details = [json.loads(row["detail"]) for row in clears if json.loads(row["detail"])["action"] == "clear"]
    assert {item["token_kind"] for item in clear_details} == {"operator", "retrieval"}


def test_verifier_write_rolls_back_when_atomic_audit_insert_fails(tmp_path, monkeypatch):
    _app_instance, db, token_config = _app(tmp_path, monkeypatch)
    original_get_conn = db.get_conn

    class FailingAuditConnection:
        def __init__(self, inner):
            self.inner = inner

        def execute(self, sql, params=()):
            if "INSERT INTO audit_log" in sql:
                raise RuntimeError("injected audit failure")
            return self.inner.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(
        db,
        "get_conn",
        lambda: FailingAuditConnection(original_get_conn()),
    )
    with pytest.raises(RuntimeError, match="injected audit failure"):
        token_config.configure(
            "operator", OPERATOR_ONE, actor_id="dev_operator", expect_unconfigured=True
        )
    monkeypatch.setattr(db, "get_conn", original_get_conn)
    assert db.fetchone(
        "SELECT value FROM system_config WHERE key='security_operator_token_v1'"
    ) is None
    assert db.fetchone(
        "SELECT id FROM audit_log WHERE event_type='security_token_configured'"
    ) is None


def test_concurrent_first_time_configuration_cannot_collapse_token_roles(tmp_path, monkeypatch):
    _app_instance, _db, token_config = _app(tmp_path, monkeypatch)
    shared_value = "shared-concurrent-token-1234"
    barrier = threading.Barrier(2)

    def configure(kind):
        barrier.wait(timeout=5)
        try:
            token_config.configure(
                kind,
                shared_value,
                actor_id="dev_operator",
                expect_unconfigured=True,
            )
            return "configured"
        except token_config.InvalidTokenValue:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(configure, ("operator", "retrieval")))
    assert sorted(results) == ["configured", "rejected"]
    configured_states = [
        token_config.get_state("operator").configured,
        token_config.get_state("retrieval").configured,
    ]
    assert configured_states.count(True) == 1


def test_mcp_config_and_runtime_key_are_local_operator_governed_and_write_only(tmp_path, monkeypatch):
    app, _db, _token_config = _app(tmp_path, monkeypatch)
    assert _request(
        app,
        "POST",
        "/api/security/tokens/operator",
        json={"token": OPERATOR_ONE},
        headers={"Origin": "http://127.0.0.1"},
    ).status_code == 200

    import app.api.routes.security_settings_routes as security_routes
    from app.core import mcp_connector

    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    monkeypatch.setattr(security_routes, "PROJECT_ROOT", runtime_root)

    config = {
        "enabled": False,
        "tunnel_id": "tun_ui-test-123",
        "oauth_issuer": "https://issuer.example/",
        "scope": "boh.read",
        "port": 4884,
    }
    configured = _request(
        app,
        "POST",
        "/api/security/mcp-connector/config",
        json=config,
        headers=_operator_headers(),
    )
    assert configured.status_code == 200
    assert configured.json()["config"]["oauth_issuer"] == "https://issuer.example/"
    assert configured.json()["config"]["auth_mode"] == "oauth_gateway"
    assert configured.json()["restart_required"] is True
    assert configured.json()["audit_recorded"] is True

    no_auth_config = {
        "enabled": False,
        "tunnel_id": "tun_ui-noauth-123",
        "auth_mode": "stdio_no_auth",
        "scope": "boh.read",
        "port": 4884,
    }
    no_auth = _request(
        app,
        "POST",
        "/api/security/mcp-connector/config",
        json=no_auth_config,
        headers=_operator_headers(),
    )
    assert no_auth.status_code == 200
    assert no_auth.json()["config"]["auth_mode"] == "stdio_no_auth"
    assert no_auth.json()["config"]["oauth_issuer"] == ""

    runtime_key = "openai-runtime-key-value-123456"
    written = _request(
        app,
        "POST",
        "/api/security/mcp-connector/runtime-key",
        json={"runtime_key": runtime_key},
        headers=_operator_headers(),
    )
    assert written.status_code == 200
    assert written.json()["runtime_key_value_returned"] is False
    assert written.json()["audit_recorded"] is True
    assert runtime_key not in written.text
    assert (runtime_root / mcp_connector.DEFAULT_RUNTIME_KEY).read_text(encoding="utf-8") == runtime_key

    status = _request(
        app, "GET", "/api/security/mcp-connector", headers=_operator_headers()
    )
    assert status.status_code == 200
    assert status.json()["status"]["runtime_key_configured"] is True
    assert status.json()["runtime_key_value_returned"] is False
    assert runtime_key not in status.text

    mcp_audits = _db.fetchall(
        "SELECT detail FROM audit_log WHERE event_type='mcp_connector_configured' ORDER BY id"
    )
    assert len(mcp_audits) == 3
    encoded_audits = json.dumps(mcp_audits)
    assert runtime_key not in encoded_audits
    assert "secret_value_recorded" in encoded_audits

    remote = _request(
        app,
        "POST",
        "/api/security/mcp-connector/runtime-key",
        client_host="192.0.2.10",
        json={"runtime_key": "another-runtime-key-123456"},
        headers=_operator_headers(origin=False),
    )
    assert remote.status_code == 403

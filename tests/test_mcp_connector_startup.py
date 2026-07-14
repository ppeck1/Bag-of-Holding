import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


class FakeProcess:
    _next_pid = 1000

    def __init__(self):
        self.pid = FakeProcess._next_pid
        FakeProcess._next_pid += 1
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.terminated or self.killed:
            self.returncode = 0
        elif self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _configured_root(
    tmp_path: Path,
    *,
    enabled=True,
    auth_mode=None,
    oauth_issuer="https://issuer.example/",
):
    from app.core import mcp_connector

    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    tunnel_client = root / mcp_connector.DEFAULT_TUNNEL_CLIENT
    tunnel_client.parent.mkdir(parents=True)
    tunnel_client.write_bytes(b"test executable placeholder")
    config = mcp_connector.ConnectorConfig(
        enabled=enabled,
        tunnel_id="tun_test-123",
        oauth_issuer=oauth_issuer,
        auth_mode=auth_mode or mcp_connector.DEFAULT_AUTH_MODE,
    )
    mcp_connector.save_config(root, config)
    mcp_connector.write_runtime_key(root, "runtime-key-value-123456")
    return root, config


def test_config_round_trip_preserves_canonical_issuer_and_contains_no_secret(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, config = _configured_root(tmp_path)
    loaded = mcp_connector.load_config(root)
    assert loaded == config
    assert loaded.oauth_issuer == "https://issuer.example/"
    assert loaded.jwks_url == "https://issuer.example/.well-known/jwks.json"

    raw = (root / mcp_connector.DEFAULT_CONFIG).read_text(encoding="utf-8")
    assert "runtime-key-value-123456" not in raw
    monkeypatch.setattr(mcp_connector, "gateway_metadata_ready", lambda _config: False)
    monkeypatch.setattr(mcp_connector, "tunnel_ready", lambda _root, _config=None: False)
    status = mcp_connector.safe_status(root)
    assert "runtime-key-value-123456" not in json.dumps(status)


def test_stdio_no_auth_config_does_not_require_oauth_issuer(tmp_path):
    from app.core import mcp_connector

    config = mcp_connector.parse_config(
        {
            "enabled": True,
            "tunnel_id": "tun_noauth-123",
            "auth_mode": mcp_connector.AUTH_MODE_STDIO_NO_AUTH,
        }
    )
    assert config.auth_mode == mcp_connector.AUTH_MODE_STDIO_NO_AUTH
    assert config.oauth_issuer == ""
    assert config.safe_dict()["auth_mode"] == mcp_connector.AUTH_MODE_STDIO_NO_AUTH


def test_connector_starter_prefers_repo_app_over_external_pythonpath(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    starter = repo_root / "tools" / "start_boh_mcp_connector.py"
    if not starter.is_file():
        pytest.skip("operational MCP starter is excluded from the sanitized export")
    foreign = tmp_path / "foreign"
    (foreign / "app" / "core").mkdir(parents=True)
    (foreign / "app" / "__init__.py").write_text("", encoding="utf-8")
    (foreign / "app" / "core" / "__init__.py").write_text(
        "raise RuntimeError('wrong app imported')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(foreign)

    result = subprocess.run(
        [
            sys.executable,
            str(starter),
            "--tunnel-id",
            "tun_test-123",
            "--auth-mode",
            "stdio_no_auth",
            "--tunnel-client",
            "custom.exe",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "wrong app imported" not in output
    assert "Custom tunnel runtime paths" in output


def test_stdio_no_auth_start_uses_direct_stdio_profile_without_gateway(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, config = _configured_root(
        tmp_path,
        auth_mode=mcp_connector.AUTH_MODE_STDIO_NO_AUTH,
        oauth_issuer="",
    )
    calls = []

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(mcp_connector, "_stdio_dependencies_available", lambda: True)
    monkeypatch.setattr(mcp_connector, "_pid_alive", lambda _path: False)
    monkeypatch.setattr(
        mcp_connector,
        "gateway_metadata_ready",
        lambda _config: (_ for _ in ()).throw(AssertionError("gateway not used")),
    )
    monkeypatch.setattr(mcp_connector, "tunnel_ready", lambda _root, _config=None: len(calls) >= 1)

    runtime = mcp_connector.start_if_enabled(
        root,
        python_executable="C:/Python/python.exe",
        spawn=spawn,
        tunnel_timeout=0.1,
        env={
            "PATH": "safe-path",
            "BOH_DB": "safe.db",
            "BOH_OPERATOR_TOKEN": "must-not-forward",
            "BOH_RETRIEVAL_TOKEN": "must-not-forward-either",
            "CONTROL_PLANE_API_KEY": "must-not-forward-control-key",
        },
    )

    assert runtime.error is None
    assert runtime.gateway_process is None
    assert runtime.tunnel_process is not None
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[0].endswith("tunnel-client.exe")
    assert command[command.index("--profile") + 1] == mcp_connector.STDIO_NO_AUTH_PROFILE
    assert command[command.index("--health.url-file") + 1].endswith(
        "boh-stdio-noauth-tunnel-client-health.url"
    )
    assert kwargs["stdout_path"].name == "boh-stdio-noauth-tunnel-client.out.log"
    assert kwargs["stderr_path"].name == "boh-stdio-noauth-tunnel-client.err.log"
    assert kwargs["env"]["BOH_MCP_EXPOSURE_MODE"] == "chatgpt_safe"
    assert kwargs["env"]["BOH_DB"] == "safe.db"
    assert "BOH_OPERATOR_TOKEN" not in kwargs["env"]
    assert "BOH_RETRIEVAL_TOKEN" not in kwargs["env"]
    assert "CONTROL_PLANE_API_KEY" not in kwargs["env"]

    profile = (
        root
        / mcp_connector.DEFAULT_PROFILE_DIR
        / f"{mcp_connector.STDIO_NO_AUTH_PROFILE}.yaml"
    ).read_text(encoding="utf-8")
    assert "commands:" in profile
    assert "server_urls:" not in profile
    assert "C:/Python/python.exe -m tools.boh_mcp_adapter.server" in profile
    assert "runtime-key-value-123456" not in profile


def test_stdio_no_auth_safe_status_uses_tunnel_readiness_without_gateway(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, config = _configured_root(
        tmp_path,
        auth_mode=mcp_connector.AUTH_MODE_STDIO_NO_AUTH,
        oauth_issuer="",
    )
    monkeypatch.setattr(mcp_connector, "_stdio_dependencies_available", lambda: True)
    monkeypatch.setattr(mcp_connector, "tunnel_ready", lambda _root, _config=None: True)
    monkeypatch.setattr(mcp_connector, "_pid_alive", lambda _path: True)
    monkeypatch.setattr(mcp_connector, "_profile_matches", lambda _root, _config, **_kwargs: True)

    status = mcp_connector.safe_status(root)
    assert status["auth_mode"] == mcp_connector.AUTH_MODE_STDIO_NO_AUTH
    assert status["gateway_ready"] is False
    assert status["tunnel_ready"] is True
    assert status["remote_ready"] is True
    assert status["restart_required"] is False


def test_stdio_no_auth_safe_status_profile_match_accepts_relative_root(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, config = _configured_root(
        tmp_path,
        auth_mode=mcp_connector.AUTH_MODE_STDIO_NO_AUTH,
        oauth_issuer="",
    )
    profile_path = (
        root
        / mcp_connector.DEFAULT_PROFILE_DIR
        / f"{mcp_connector.STDIO_NO_AUTH_PROFILE}.yaml"
    )
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        mcp_connector._tunnel_profile_content(root, config),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mcp_connector, "_stdio_dependencies_available", lambda: True)
    monkeypatch.setattr(mcp_connector, "tunnel_ready", lambda _root, _config=None: True)
    monkeypatch.setattr(mcp_connector, "_pid_alive", lambda _path: True)

    status = mcp_connector.safe_status(Path("repo"))
    assert status["auth_mode"] == mcp_connector.AUTH_MODE_STDIO_NO_AUTH
    assert status["tunnel_ready"] is True
    assert status["remote_ready"] is True
    assert status["restart_required"] is False


def test_gateway_metadata_requires_exact_issuer_jwks_resource_and_scope(tmp_path, monkeypatch):
    from app.core import mcp_connector

    _root, config = _configured_root(tmp_path)
    payload = {
        "resource": config.resource_url,
        "authorization_servers": [config.oauth_issuer],
        "jwks_uri": config.jwks_url,
        "scopes_supported": [config.scope],
    }
    profile = {
        "name": "BOH MCP Gateway",
        "transport": "streamable-http",
        "mcpEndpoint": "/mcp",
        "auth": {"mode": "oauth", "scope": config.scope},
        "profile": "remote_readonly",
        "allowedTools": list(mcp_connector.EXPECTED_REMOTE_TOOLS),
    }
    monkeypatch.setattr(
        mcp_connector,
        "_read_json_url",
        lambda url, timeout=2.0: profile if url.endswith("/.well-known/boh-mcp") else payload,
    )
    assert mcp_connector.gateway_metadata_ready(config) is True

    payload["authorization_servers"] = [config.oauth_issuer.rstrip("/")]
    assert mcp_connector.gateway_metadata_ready(config) is False
    payload["authorization_servers"] = [config.oauth_issuer]
    payload["jwks_uri"] = "https://issuer.example/wrong.json"
    assert mcp_connector.gateway_metadata_ready(config) is False
    payload["jwks_uri"] = config.jwks_url
    profile["allowedTools"] = list(mcp_connector.EXPECTED_REMOTE_TOOLS[:-1])
    assert mcp_connector.gateway_metadata_ready(config) is False


def test_tunnel_ready_accepts_plain_text_readyz_on_loopback(tmp_path, monkeypatch):
    from app.core import mcp_connector

    health_file = tmp_path / mcp_connector.DEFAULT_RUNS_DIR / "boh-tunnel-client-health.url"
    health_file.parent.mkdir(parents=True)
    health_file.write_text("http://127.0.0.1:43210\n", encoding="utf-8")
    requested = []
    monkeypatch.setattr(
        mcp_connector,
        "_http_ready",
        lambda url, timeout=2.0: requested.append(url) or True,
    )
    assert mcp_connector.tunnel_ready(tmp_path) is True
    assert requested == ["http://127.0.0.1:43210/readyz"]


def test_concurrent_runtime_key_writes_use_unique_atomic_temp_files(tmp_path):
    from app.core import mcp_connector

    values = [f"runtime-key-concurrent-{index:02d}-value" for index in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda value: mcp_connector.write_runtime_key(tmp_path, value), values))
    target = tmp_path / mcp_connector.DEFAULT_RUNTIME_KEY
    assert target.read_text(encoding="utf-8") in values
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "nt", reason="Windows process probe regression")
def test_windows_pid_probe_does_not_terminate_existing_process(tmp_path):
    from app.core import mcp_connector

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        pid_file = tmp_path / "process.pid"
        pid_file.write_text(str(process.pid), encoding="utf-8")
        assert mcp_connector._pid_alive(pid_file) is True
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_missing_or_disabled_config_is_noop(tmp_path, monkeypatch):
    from app.core import mcp_connector

    def fail_spawn(*_args, **_kwargs):
        raise AssertionError("spawn must not be called")

    missing = mcp_connector.start_if_enabled(tmp_path, spawn=fail_spawn)
    assert missing.safe_dict() == {
        "configured": False,
        "enabled": False,
        "gateway_started": False,
        "tunnel_started": False,
        "gateway_reused": False,
        "tunnel_reused": False,
        "error": None,
    }

    root, _config = _configured_root(tmp_path, enabled=False)
    disabled = mcp_connector.start_if_enabled(root, spawn=fail_spawn)
    assert disabled.configured is True
    assert disabled.enabled is False
    assert disabled.error is None


def test_enabled_config_starts_gateway_and_tunnel_once_and_stops_owned_children(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, config = _configured_root(tmp_path)
    calls = []
    processes = []

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(mcp_connector, "_connector_dependencies_available", lambda: True)
    monkeypatch.setattr(mcp_connector, "_port_in_use", lambda _port: False)
    monkeypatch.setattr(mcp_connector, "_pid_alive", lambda _path: False)
    monkeypatch.setattr(mcp_connector, "gateway_metadata_ready", lambda _config: len(calls) >= 1)
    monkeypatch.setattr(mcp_connector, "tunnel_ready", lambda _root, _config=None: len(calls) >= 2)

    runtime = mcp_connector.start_if_enabled(
        root,
        python_executable="python-test",
        spawn=spawn,
        metadata_timeout=0.1,
        tunnel_timeout=0.1,
        env={
            "PATH": "safe-path",
            "BOH_DB": "safe.db",
            "BOH_OPERATOR_TOKEN": "must-not-forward",
            "BOH_RETRIEVAL_TOKEN": "must-not-forward-either",
            "CONTROL_PLANE_API_KEY": "must-not-forward-control-key",
        },
    )
    assert runtime.error is None
    assert len(calls) == 2
    gateway_command = calls[0][0]
    tunnel_command = calls[1][0]
    assert gateway_command[0:2] == ["python-test", "tools/boh_mcp_gateway.py"]
    assert gateway_command[gateway_command.index("--python") + 1] == "python-test"
    assert Path(gateway_command[gateway_command.index("--cwd") + 1]) == root
    assert gateway_command[gateway_command.index("--authorization-server") + 1] == config.oauth_issuer
    assert gateway_command[gateway_command.index("--jwks-url") + 1] == config.jwks_url
    assert "runtime-key-value-123456" not in " ".join(gateway_command + tunnel_command)
    for _command, kwargs in calls:
        assert kwargs["env"]["BOH_DB"] == "safe.db"
        assert kwargs["env"]["PATH"] == "safe-path"
        assert "BOH_OPERATOR_TOKEN" not in kwargs["env"]
        assert "BOH_RETRIEVAL_TOKEN" not in kwargs["env"]
        assert "CONTROL_PLANE_API_KEY" not in kwargs["env"]

    runtime.stop()
    assert all(process.terminated for process in processes)


def test_healthy_existing_connector_is_reused_without_spawn(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, _config = _configured_root(tmp_path)
    monkeypatch.setattr(mcp_connector, "_connector_dependencies_available", lambda: False)
    monkeypatch.setattr(mcp_connector, "gateway_metadata_ready", lambda _config: True)
    monkeypatch.setattr(mcp_connector, "tunnel_ready", lambda _root, _config=None: True)
    monkeypatch.setattr(mcp_connector, "_pid_alive", lambda _path: True)
    monkeypatch.setattr(mcp_connector, "_profile_matches", lambda _root, _config, **_kwargs: True)

    (root / mcp_connector.DEFAULT_TUNNEL_CLIENT).unlink()
    (root / mcp_connector.DEFAULT_RUNTIME_KEY).unlink()

    runtime = mcp_connector.start_if_enabled(
        root,
        spawn=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("duplicate spawn")),
    )
    assert runtime.error is None
    assert runtime.gateway_reused is True
    assert runtime.tunnel_reused is True
    runtime.stop()


def test_ready_tunnel_with_changed_profile_is_not_falsely_reused(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, _config = _configured_root(tmp_path)
    old_profile = root / mcp_connector.DEFAULT_PROFILE_DIR / "boh.yaml"
    old_profile.parent.mkdir(parents=True, exist_ok=True)
    old_profile.write_text("tunnel_id: old-tunnel\n", encoding="utf-8")
    monkeypatch.setattr(mcp_connector, "gateway_metadata_ready", lambda _config: True)
    monkeypatch.setattr(mcp_connector, "tunnel_ready", lambda _root, _config=None: True)
    monkeypatch.setattr(mcp_connector, "_pid_alive", lambda _path: True)

    runtime = mcp_connector.start_if_enabled(root)
    assert runtime.error == "mcp_tunnel_config_mismatch"
    assert old_profile.read_text(encoding="utf-8") == "tunnel_id: old-tunnel\n"


def test_stale_gateway_metadata_on_occupied_port_fails_without_duplicate(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, _config = _configured_root(tmp_path)
    monkeypatch.setattr(mcp_connector, "_connector_dependencies_available", lambda: True)
    monkeypatch.setattr(mcp_connector, "gateway_metadata_ready", lambda _config: False)
    monkeypatch.setattr(mcp_connector, "_port_in_use", lambda _port: True)

    runtime = mcp_connector.start_if_enabled(
        root,
        spawn=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("duplicate spawn")),
    )
    assert runtime.error == "mcp_gateway_metadata_mismatch"
    assert runtime.gateway_process is None
    assert runtime.tunnel_process is None


def test_connector_lock_prevents_two_launchers_from_claiming_same_runtime(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, _config = _configured_root(tmp_path)
    monkeypatch.setattr(mcp_connector, "gateway_metadata_ready", lambda _config: True)
    monkeypatch.setattr(mcp_connector, "tunnel_ready", lambda _root, _config=None: True)
    monkeypatch.setattr(mcp_connector, "_pid_alive", lambda _path: True)
    monkeypatch.setattr(mcp_connector, "_profile_matches", lambda _root, _config, **_kwargs: True)

    owner = mcp_connector.start_if_enabled(root)
    assert owner.error is None
    contender = mcp_connector.start_if_enabled(root)
    assert contender.error == "mcp_connector_owned_by_another_launcher"
    owner.stop()

    successor = mcp_connector.start_if_enabled(root)
    assert successor.error is None
    assert successor.gateway_reused and successor.tunnel_reused
    successor.stop()


def test_interrupted_startup_stops_spawned_child_and_releases_lock(tmp_path, monkeypatch):
    from app.core import mcp_connector

    root, _config = _configured_root(tmp_path)
    spawned = []

    def spawn(*_args, **_kwargs):
        process = FakeProcess()
        spawned.append(process)
        return process

    monkeypatch.setattr(mcp_connector, "gateway_metadata_ready", lambda _config: False)
    monkeypatch.setattr(mcp_connector, "_port_in_use", lambda _port: False)
    monkeypatch.setattr(mcp_connector, "_connector_dependencies_available", lambda: True)
    monkeypatch.setattr(
        mcp_connector,
        "_wait_until",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        mcp_connector.start_if_enabled(root, spawn=spawn)
    assert spawned and spawned[0].terminated is True

    lock = mcp_connector._try_startup_lock(root)
    assert lock is not None
    mcp_connector._release_startup_lock(lock)


def test_stubborn_tunnel_cleanup_does_not_skip_gateway_cleanup():
    from app.core import mcp_connector

    class StubbornProcess(FakeProcess):
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("stubborn", timeout)

    tunnel = StubbornProcess()
    gateway = FakeProcess()
    runtime = mcp_connector.ConnectorRuntime(
        configured=True,
        enabled=True,
        gateway_process=gateway,
        tunnel_process=tunnel,
    )
    runtime.stop()
    assert tunnel.terminated is True
    assert tunnel.killed is True
    assert gateway.terminated is True


def test_launcher_no_mcp_flag_keeps_normal_server_path(monkeypatch):
    import launcher

    assert launcher.parse_args(["--no-mcp"]).no_mcp is True
    launched = []

    class ServerProcess(FakeProcess):
        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    monkeypatch.setattr(launcher, "dependency_preflight", lambda: None)
    monkeypatch.setattr(launcher, "preflight_check", lambda _root: [])
    monkeypatch.setattr(launcher, "port_is_open", lambda _host, _port: False)
    monkeypatch.setattr(launcher, "wait_for_ready", lambda _url: True)
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(launcher.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda command, **_kwargs: launched.append(command) or ServerProcess(),
    )

    assert launcher.main(["--no-browser", "--no-mcp"]) == 0
    assert len(launched) == 1
    assert "uvicorn" in launched[0]


def test_launcher_connector_failure_is_fail_soft_and_owned_runtime_is_stopped(monkeypatch):
    import launcher
    from app.core import mcp_connector

    class FailedRuntime:
        stopped = False

        def safe_dict(self):
            return {
                "configured": True,
                "enabled": True,
                "gateway_started": False,
                "tunnel_started": False,
                "gateway_reused": False,
                "tunnel_reused": False,
                "error": "mcp_dependency_missing",
            }

        def stop(self):
            self.stopped = True

    runtime = FailedRuntime()
    server = FakeProcess()
    events = []
    monkeypatch.setattr(launcher, "dependency_preflight", lambda: None)
    monkeypatch.setattr(launcher, "preflight_check", lambda _root: [])
    monkeypatch.setattr(launcher, "port_is_open", lambda _host, _port: False)
    monkeypatch.setattr(launcher, "wait_for_ready", lambda _url: True)
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(launcher.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        mcp_connector,
        "start_if_enabled",
        lambda *_args, **_kwargs: events.append("mcp") or runtime,
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda *_args, **_kwargs: events.append("uvicorn") or server,
    )

    assert launcher.main(["--no-browser"]) == 0
    assert server.returncode == 0
    assert runtime.stopped is True
    assert events == ["uvicorn", "mcp"]


def test_launcher_uvicorn_spawn_failure_never_starts_mcp(monkeypatch):
    import launcher
    from app.core import mcp_connector

    monkeypatch.setattr(launcher, "dependency_preflight", lambda: None)
    monkeypatch.setattr(launcher, "preflight_check", lambda _root: [])
    monkeypatch.setattr(launcher, "port_is_open", lambda _host, _port: False)
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("injected")),
    )
    monkeypatch.setattr(
        mcp_connector,
        "start_if_enabled",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("MCP started before Uvicorn")
        ),
    )
    with pytest.raises(SystemExit) as exc:
        launcher.main(["--no-browser"])
    assert exc.value.code == 1

"""Opt-in local lifecycle and write-only configuration for BOH MCP.

The launcher owns only processes started by the current launcher invocation.
Existing healthy gateway/tunnel processes are reused and never terminated.
Configuration and the tunnel runtime key live under the ignored ``.local``
tree; the key is write-only through this module.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


DEFAULT_CONFIG = Path(".local/boh_mcp_connector_autostart.json")
DEFAULT_TUNNEL_CLIENT = Path(".local/tunnel-client/tunnel-client.exe")
DEFAULT_RUNTIME_KEY = Path(".local/secrets/openai_tunnel_runtime_key.txt")
DEFAULT_PROFILE_DIR = Path(".local/tunnel-client/profiles")
DEFAULT_RUNS_DIR = Path(".local/runs")
DEFAULT_PROFILE = "boh"
DEFAULT_SCOPE = "boh.read"
DEFAULT_PORT = 4884
AUTH_MODE_OAUTH_GATEWAY = "oauth_gateway"
AUTH_MODE_STDIO_NO_AUTH = "stdio_no_auth"
DEFAULT_AUTH_MODE = AUTH_MODE_OAUTH_GATEWAY
STDIO_NO_AUTH_PROFILE = "boh-stdio-noauth"
EXPECTED_REMOTE_TOOLS = (
    "health",
    "current_context_brief",
    "search_context",
    "retrieve_context",
    "assemble_context_pack",
    "run_validation_profile",
    "latest_validation_report",
    "publication_gate",
)
_TUNNEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,199}$")
_ATOMIC_WRITE_LOCKS: dict[str, threading.Lock] = {}
_ATOMIC_WRITE_LOCKS_GUARD = threading.Lock()


class ConnectorConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ConnectorConfig:
    enabled: bool
    tunnel_id: str
    oauth_issuer: str = ""
    scope: str = DEFAULT_SCOPE
    port: int = DEFAULT_PORT
    auth_mode: str = DEFAULT_AUTH_MODE

    @property
    def resource_url(self) -> str:
        return f"https://api.openai.com/v1/tunnel/{self.tunnel_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.oauth_issuer.rstrip('/')}/.well-known/jwks.json"

    @property
    def metadata_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/.well-known/oauth-protected-resource"

    @property
    def gateway_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "tunnel_id": self.tunnel_id,
            "oauth_issuer": self.oauth_issuer,
            "scope": self.scope,
            "port": self.port,
            "auth_mode": self.auth_mode,
        }


@dataclass
class ConnectorRuntime:
    configured: bool = False
    enabled: bool = False
    gateway_process: Any | None = None
    tunnel_process: Any | None = None
    gateway_reused: bool = False
    tunnel_reused: bool = False
    error: str | None = None
    _lock_handle: Any | None = field(default=None, repr=False)

    def stop(self) -> None:
        """Stop only children created by this runtime, tunnel first."""
        for process in (self.tunnel_process, self.gateway_process):
            try:
                _terminate_owned(process)
            except Exception:
                # One stubborn child must not prevent cleanup of the other.
                pass
        self.tunnel_process = None
        self.gateway_process = None
        _release_startup_lock(self._lock_handle)
        self._lock_handle = None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "gateway_started": self.gateway_process is not None,
            "tunnel_started": self.tunnel_process is not None,
            "gateway_reused": self.gateway_reused,
            "tunnel_reused": self.tunnel_reused,
            "error": self.error,
        }


def _config_path(root: Path, path: Path | None = None) -> Path:
    return path if path is not None else root / DEFAULT_CONFIG


def _validate_issuer(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConnectorConfigError("oauth issuer is required")
    issuer = value.strip()
    parsed = urlsplit(issuer)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ConnectorConfigError("oauth issuer must be an HTTPS issuer URL")
    return issuer


def parse_config(payload: object) -> ConnectorConfig:
    if not isinstance(payload, dict):
        raise ConnectorConfigError("connector configuration must be an object")
    allowed = {"enabled", "tunnel_id", "oauth_issuer", "scope", "port", "auth_mode"}
    unknown = set(payload) - allowed
    if unknown:
        raise ConnectorConfigError("connector configuration contains unsupported fields")
    auth_mode = payload.get("auth_mode", DEFAULT_AUTH_MODE)
    if auth_mode not in {AUTH_MODE_OAUTH_GATEWAY, AUTH_MODE_STDIO_NO_AUTH}:
        raise ConnectorConfigError("auth mode must be oauth_gateway or stdio_no_auth")
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ConnectorConfigError("enabled must be true or false")
    tunnel_id = payload.get("tunnel_id")
    if not isinstance(tunnel_id, str) or not _TUNNEL_ID_RE.fullmatch(tunnel_id):
        raise ConnectorConfigError("tunnel id has an invalid format")
    issuer_value = payload.get("oauth_issuer", "")
    if auth_mode == AUTH_MODE_OAUTH_GATEWAY:
        issuer = _validate_issuer(issuer_value)
    else:
        issuer = _validate_issuer(issuer_value) if issuer_value else ""
    scope = payload.get("scope", DEFAULT_SCOPE)
    if scope != DEFAULT_SCOPE:
        raise ConnectorConfigError(f"scope must remain {DEFAULT_SCOPE}")
    port = payload.get("port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ConnectorConfigError("gateway port must be between 1024 and 65535")
    return ConnectorConfig(enabled, tunnel_id, issuer, scope, port, auth_mode)


def load_config(root: Path, path: Path | None = None) -> ConnectorConfig | None:
    target = _config_path(root, path)
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConnectorConfigError("connector configuration is unreadable") from exc
    return parse_config(payload)


def _atomic_write(path: Path, value: str, *, secret_file: bool = False) -> None:
    lock_key = str(path.resolve(strict=False)).casefold()
    with _ATOMIC_WRITE_LOCKS_GUARD:
        write_lock = _ATOMIC_WRITE_LOCKS.setdefault(lock_key, threading.Lock())
    with write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            if secret_file:
                try:
                    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
            for attempt in range(6):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if os.name == "nt" and path.exists():
                        try:
                            # Windows replacement refuses a read-only target.
                            path.chmod(stat.S_IREAD | stat.S_IWRITE)
                        except OSError:
                            pass
                    if attempt == 5:
                        raise
                    time.sleep(0.05 * (attempt + 1))
            if secret_file:
                try:
                    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def save_config(root: Path, config: ConnectorConfig, path: Path | None = None) -> None:
    target = _config_path(root, path)
    _atomic_write(target, json.dumps(config.safe_dict(), indent=2, sort_keys=True) + "\n")


def disable_config(root: Path, path: Path | None = None) -> ConnectorConfig:
    config = load_config(root, path)
    if config is None:
        raise ConnectorConfigError("connector is not configured")
    disabled = ConnectorConfig(
        False,
        config.tunnel_id,
        config.oauth_issuer,
        config.scope,
        config.port,
        config.auth_mode,
    )
    save_config(root, disabled, path)
    return disabled


def runtime_key_path(root: Path) -> Path:
    return (root / DEFAULT_RUNTIME_KEY).resolve(strict=False)


def runtime_key_configured(root: Path) -> bool:
    try:
        return runtime_key_path(root).is_file() and runtime_key_path(root).stat().st_size > 0
    except OSError:
        return False


def write_runtime_key(root: Path, value: str) -> None:
    if (
        not isinstance(value, str)
        or not 16 <= len(value) <= 4096
        or value != value.strip()
        or any(ch.isspace() or not ch.isprintable() for ch in value)
    ):
        raise ConnectorConfigError("runtime key must be 16-4096 printable non-whitespace characters")
    target = runtime_key_path(root)
    _atomic_write(target, value, secret_file=True)


def _read_json_url(url: str, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (OSError, urllib.error.URLError, UnicodeError, json.JSONDecodeError):
        return None


def _http_ready(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            # Tunnel-client /readyz intentionally returns plain text.
            response.read(4096)
            return getattr(response, "status", 200) == 200
    except (OSError, urllib.error.URLError):
        return False


def gateway_metadata_ready(config: ConnectorConfig) -> bool:
    if config.auth_mode != AUTH_MODE_OAUTH_GATEWAY:
        return False
    payload = _read_json_url(config.metadata_url)
    profile = _read_json_url(
        f"http://127.0.0.1:{config.port}/.well-known/boh-mcp"
    )
    return bool(
        payload
        and payload.get("resource") == config.resource_url
        and payload.get("authorization_servers") == [config.oauth_issuer]
        and payload.get("jwks_uri") == config.jwks_url
        and config.scope in payload.get("scopes_supported", [])
        and profile
        and profile.get("name") == "BOH MCP Gateway"
        and profile.get("transport") == "streamable-http"
        and profile.get("mcpEndpoint") == "/mcp"
        and profile.get("profile") == "remote_readonly"
        and profile.get("allowedTools") == list(EXPECTED_REMOTE_TOOLS)
        and profile.get("auth", {}).get("mode") == "oauth"
        and profile.get("auth", {}).get("scope") == config.scope
    )


def _loopback_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        return False
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return parsed.hostname.casefold() == "localhost"
    return address.is_loopback


def tunnel_ready(root: Path, config: ConnectorConfig | None = None) -> bool:
    health_file = _tunnel_health_file(root, config)
    try:
        health_base = health_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return False
    if not _loopback_http_url(health_base):
        return False
    return _http_ready(f"{health_base.rstrip('/')}/readyz")


def _profile_name(config: ConnectorConfig) -> str:
    if config.auth_mode == AUTH_MODE_STDIO_NO_AUTH:
        return STDIO_NO_AUTH_PROFILE
    return DEFAULT_PROFILE


def _run_stem(config: ConnectorConfig) -> str:
    if config.auth_mode == AUTH_MODE_STDIO_NO_AUTH:
        return "boh-stdio-noauth-tunnel-client"
    return "boh-tunnel-client"


def _tunnel_health_file(root: Path, config: ConnectorConfig | None = None) -> Path:
    stem = _run_stem(config) if config is not None else "boh-tunnel-client"
    return root / DEFAULT_RUNS_DIR / f"{stem}-health.url"


def _tunnel_pid_file(root: Path, config: ConnectorConfig) -> Path:
    return root / DEFAULT_RUNS_DIR / f"{_run_stem(config)}.pid"


def _stdio_mcp_command(python_executable: str | None = None) -> str:
    executable = str(Path(python_executable or sys.executable)).replace("\\", "/")
    return f"{executable} -m tools.boh_mcp_adapter.server"


def _port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _pid_alive(path: Path) -> bool:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        if pid <= 0:
            return False
        if os.name == "nt":
            # Unlike POSIX, os.kill(pid, 0) is not a harmless liveness probe on
            # Windows: Python routes it through TerminateProcess. Query the
            # process handle without mutating the existing tunnel instead.
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if not handle:
                # Access denied means the process exists but is not queryable.
                return ctypes.get_last_error() == 5
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, UnicodeError, ValueError):
        return False


def connector_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Build the minimal non-secret environment needed by gateway/tunnel children."""
    source = dict(os.environ if source is None else source)
    allowed = {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
        "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
        "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "VIRTUAL_ENV",
        "PYTHONHOME", "PYTHONUTF8", "PYTHONIOENCODING", "LANG", "LC_ALL",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE",
        "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
        # Read-only BOH coordinates required by the stdio adapter.
        "BOH_DB", "BOH_LIBRARY", "BOH_DATA_ROOT",
        "BOH_RETRIEVAL_INCLUDE_PROMOTED",
    }
    safe = {key: value for key, value in source.items() if key.upper() in allowed}
    safe["BOH_MCP_EXPOSURE_MODE"] = "chatgpt_safe"
    return safe


def _try_startup_lock(root: Path) -> Any | None:
    """Acquire a non-blocking interprocess lock held for connector ownership."""
    lock_path = root / DEFAULT_RUNS_DIR / "boh-mcp-connector.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except (OSError, BlockingIOError):
        handle.close()
        return None


def _release_startup_lock(handle: Any | None) -> None:
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError):
        pass
    finally:
        try:
            handle.close()
        except OSError:
            pass


def _connector_dependencies_available() -> bool:
    return (
        importlib.util.find_spec("jwt") is not None
        and importlib.util.find_spec("cryptography") is not None
        and importlib.util.find_spec("mcp") is not None
    )


def _stdio_dependencies_available() -> bool:
    return importlib.util.find_spec("mcp") is not None


def _dependencies_available(config: ConnectorConfig) -> bool:
    if config.auth_mode == AUTH_MODE_STDIO_NO_AUTH:
        return _stdio_dependencies_available()
    return _connector_dependencies_available()


def _spawn_logged(
    command: list[str],
    *,
    root: Path,
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str] | None,
) -> subprocess.Popen[bytes]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        return subprocess.Popen(
            command,
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            close_fds=True,
            creationflags=creationflags,
        )


def _wait_until(check: Callable[[], bool], timeout: float, process: Any | None = None) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(0.25)
    return False


def _terminate_owned(process: Any | None) -> None:
    if process is None:
        return
    try:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        pass


def _tunnel_profile_content(
    root: Path,
    config: ConnectorConfig,
    *,
    python_executable: str | None = None,
) -> str:
    key_path = runtime_key_path(root)
    key_yaml = json.dumps(str(key_path).replace("\\", "/"))
    tunnel_yaml = json.dumps(config.tunnel_id)
    lines = [
        "config_version: 1",
        "control_plane:",
        '  base_url: "https://api.openai.com"',
        "",
        f"  tunnel_id: {tunnel_yaml}",
        f"  api_key: \"file:{key_yaml[1:-1]}\"",
        "health:",
        '  listen_addr: "127.0.0.1:0"',
        "admin_ui:",
        "  open_browser: false",
        "log:",
        "  level: info",
        "  format: json",
        "mcp:",
    ]
    if config.auth_mode == AUTH_MODE_STDIO_NO_AUTH:
        command_yaml = json.dumps(_stdio_mcp_command(python_executable))
        lines.extend(
            [
                "  commands:",
                "    - channel: main",
                f"      command: {command_yaml}",
                "",
            ]
        )
    else:
        gateway_yaml = json.dumps(config.gateway_url)
        lines.extend(
            [
                "  server_urls:",
                "    - channel: main",
                f"      url: {gateway_yaml}",
                "",
            ]
        )
    return "\n".join(lines)


def _profile_matches(
    root: Path,
    config: ConnectorConfig,
    *,
    python_executable: str | None = None,
) -> bool:
    profile_path = root / DEFAULT_PROFILE_DIR / f"{_profile_name(config)}.yaml"
    try:
        return profile_path.read_text(encoding="utf-8") == _tunnel_profile_content(
            root,
            config,
            python_executable=python_executable,
        )
    except (OSError, UnicodeError):
        return False


def _write_tunnel_profile(
    root: Path,
    config: ConnectorConfig,
    *,
    python_executable: str | None = None,
) -> Path:
    profile_path = root / DEFAULT_PROFILE_DIR / f"{_profile_name(config)}.yaml"
    _atomic_write(
        profile_path,
        _tunnel_profile_content(root, config, python_executable=python_executable),
    )
    return profile_path


def start_if_enabled(
    root: Path,
    *,
    path: Path | None = None,
    python_executable: str | None = None,
    env: dict[str, str] | None = None,
    spawn: Callable[..., Any] | None = None,
    metadata_timeout: float = 15.0,
    tunnel_timeout: float = 20.0,
) -> ConnectorRuntime:
    """Start/reuse the connector, returning redacted fail-soft state."""
    runtime = ConnectorRuntime()
    spawn_process = spawn or _spawn_logged
    try:
        config = load_config(root, path)
        if config is None:
            return runtime
        runtime.configured = True
        runtime.enabled = config.enabled
        if not config.enabled:
            return runtime

        runtime._lock_handle = _try_startup_lock(root)
        if runtime._lock_handle is None:
            runtime.error = "mcp_connector_owned_by_another_launcher"
            return runtime

        # Re-read after locking so a concurrent Settings save cannot leave this
        # startup using a stale configuration snapshot.
        config = load_config(root, path)
        if config is None or not config.enabled:
            runtime.enabled = bool(config and config.enabled)
            runtime.stop()
            return runtime

        child_env = connector_environment(env)

        runs_dir = root / DEFAULT_RUNS_DIR
        runs_dir.mkdir(parents=True, exist_ok=True)
        pid_file = _tunnel_pid_file(root, config)

        gateway_ready = (
            config.auth_mode == AUTH_MODE_OAUTH_GATEWAY
            and gateway_metadata_ready(config)
        )
        tunnel_http_ready = tunnel_ready(root, config)
        tunnel_identity_ready = (
            tunnel_http_ready
            and _pid_alive(pid_file)
            and _profile_matches(root, config, python_executable=python_executable)
        )

        # A fully healthy pre-existing connector can be reused without local
        # spawn dependencies or key material.
        if config.auth_mode == AUTH_MODE_STDIO_NO_AUTH and tunnel_identity_ready:
            runtime.tunnel_reused = True
            return runtime
        if config.auth_mode == AUTH_MODE_OAUTH_GATEWAY and gateway_ready and tunnel_identity_ready:
            runtime.gateway_reused = True
            runtime.tunnel_reused = True
            return runtime

        if config.auth_mode == AUTH_MODE_OAUTH_GATEWAY:
            if gateway_ready:
                runtime.gateway_reused = True
            else:
                if _port_in_use(config.port):
                    runtime.error = "mcp_gateway_metadata_mismatch"
                    runtime.stop()
                    return runtime
                if not _dependencies_available(config):
                    runtime.error = "mcp_dependency_missing"
                    runtime.stop()
                    return runtime
                runtime.gateway_process = spawn_process(
                    [
                        python_executable or sys.executable,
                        "tools/boh_mcp_gateway.py",
                        "--python", python_executable or sys.executable,
                        "--cwd", str(root),
                        "--host", "127.0.0.1",
                        "--port", str(config.port),
                        "--auth-mode", "oauth",
                        "--resource-url", config.resource_url,
                        "--authorization-server", config.oauth_issuer,
                        "--jwks-url", config.jwks_url,
                        "--scope", config.scope,
                        "--allowed-origin", "https://chatgpt.com",
                    ],
                    root=root,
                    stdout_path=runs_dir / "boh-mcp-gateway.out.log",
                    stderr_path=runs_dir / "boh-mcp-gateway.err.log",
                    env=child_env,
                )
                if not _wait_until(
                    lambda: gateway_metadata_ready(config),
                    metadata_timeout,
                    runtime.gateway_process,
                ):
                    runtime.error = "mcp_gateway_not_ready"
                    runtime.stop()
                    return runtime
        elif not _dependencies_available(config):
            runtime.error = "mcp_dependency_missing"
            runtime.stop()
            return runtime

        # A ready listener is reusable only when its PID is live and the
        # existing profile still matches this exact tunnel ID/gateway target.
        tunnel_http_ready = tunnel_ready(root, config)
        tunnel_pid_alive = _pid_alive(pid_file)
        profile_matches = _profile_matches(root, config, python_executable=python_executable)
        if tunnel_http_ready:
            if tunnel_pid_alive and profile_matches:
                runtime.tunnel_reused = True
                return runtime
            runtime.error = "mcp_tunnel_config_mismatch"
            runtime.stop()
            return runtime

        if tunnel_pid_alive:
            if not profile_matches:
                runtime.error = "mcp_tunnel_config_mismatch"
                runtime.stop()
                return runtime
            if _wait_until(lambda: tunnel_ready(root, config), tunnel_timeout):
                runtime.tunnel_reused = True
                return runtime
            runtime.error = "mcp_existing_tunnel_unhealthy"
            runtime.stop()
            return runtime

        tunnel_client = root / DEFAULT_TUNNEL_CLIENT
        if not tunnel_client.is_file() or not runtime_key_configured(root):
            runtime.error = "mcp_runtime_file_missing"
            runtime.stop()
            return runtime
        profile_path = _write_tunnel_profile(
            root,
            config,
            python_executable=python_executable,
        )
        run_stem = _run_stem(config)

        runtime.tunnel_process = spawn_process(
            [
                str(tunnel_client),
                "run",
                "--profile", _profile_name(config),
                "--profile-dir", str(profile_path.parent),
                "--health.url-file", str(_tunnel_health_file(root, config)),
                "--pid.file", str(pid_file),
                "--log.file", str(runs_dir / f"{run_stem}.log"),
                "--log.format", "json",
            ],
            root=root,
            stdout_path=runs_dir / f"{run_stem}.out.log",
            stderr_path=runs_dir / f"{run_stem}.err.log",
            env=child_env,
        )
        if not _wait_until(
            lambda: tunnel_ready(root, config),
            tunnel_timeout,
            runtime.tunnel_process,
        ):
            runtime.error = "mcp_tunnel_not_ready"
            runtime.stop()
            return runtime
        return runtime
    except (KeyboardInterrupt, SystemExit):
        runtime.stop()
        raise
    except ConnectorConfigError:
        runtime.error = "mcp_config_invalid"
        runtime.stop()
        return runtime
    except Exception as exc:
        runtime.error = f"mcp_start_failed:{type(exc).__name__}"
        runtime.stop()
        return runtime


def safe_status(root: Path, path: Path | None = None) -> dict[str, Any]:
    """Return non-secret connector state for status/UI surfaces."""
    result: dict[str, Any] = {
        "configured": False,
        "config_valid": True,
        "enabled": False,
        "auth_mode": DEFAULT_AUTH_MODE,
        "runtime_key_configured": runtime_key_configured(root),
        "dependencies_ready": _connector_dependencies_available(),
        "gateway_ready": False,
        "tunnel_ready": False,
        "remote_ready": False,
        "restart_required": True,
    }
    try:
        config = load_config(root, path)
    except ConnectorConfigError:
        result["configured"] = True
        result["config_valid"] = False
        return result
    if config is None:
        return result
    result.update(
        {
            "configured": True,
            "enabled": config.enabled,
            "auth_mode": config.auth_mode,
            "dependencies_ready": _dependencies_available(config),
        }
    )
    if not config.enabled:
        return result
    gateway = gateway_metadata_ready(config)
    pid_file = _tunnel_pid_file(root, config)
    tunnel = (
        tunnel_ready(root, config)
        and _pid_alive(pid_file)
        and _profile_matches(root, config)
    )
    remote_ready = tunnel if config.auth_mode == AUTH_MODE_STDIO_NO_AUTH else gateway and tunnel
    result.update(
        {
            "gateway_ready": gateway,
            "tunnel_ready": tunnel,
            "remote_ready": remote_ready,
            "restart_required": not remote_ready,
        }
    )
    return result

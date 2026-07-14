"""launcher.py: Desktop launcher for Bag of Holding.

Double-click (or run: python launcher.py) to start the server and open the browser.
No uvicorn command knowledge required.

Usage:
    python launcher.py                  # default port 8000
    python launcher.py --port 9000      # custom port
    python launcher.py --no-browser     # headless / server-only
    python launcher.py --no-mcp         # skip configured MCP autostart
    python launcher.py --library /path  # set library root at launch

URLs once running:
    http://127.0.0.1:8000/        governed UI  (primary)
    http://127.0.0.1:8000/classic classic UI   (legacy — preserved for rollback only)
    http://127.0.0.1:8000/api/    API routes
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# -- Constants -----------------------------------------------------------------
DEFAULT_PORT    = 8000
DEFAULT_HOST    = "127.0.0.1"
STARTUP_WAIT_S  = 2.5      # seconds to wait before polling health
MAX_WAIT_S      = 14.0     # max wait before giving up on health check
HEALTH_ENDPOINT = "/api/health"

# -- Resolve project root ------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.resolve()


# -- Dependency check ----------------------------------------------------------
REQUIRED_PACKAGES = {
    # import-name : pip install name
    "fastapi":    "fastapi",
    "uvicorn":    "uvicorn",
    "pydantic":   "pydantic",
    "yaml":       "PyYAML",
    "multipart":  "python-multipart",
    "starlette":  "starlette",
}

def check_dependencies() -> list[tuple[str, str]]:
    """Return list of (import_name, pip_name) for missing packages."""
    import importlib.util
    missing = []
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(import_name) is None:
            missing.append((import_name, pip_name))
    return missing


def dependency_preflight() -> None:
    """Check all required packages are installed. Print fix instructions and exit if not."""
    missing = check_dependencies()
    if not missing:
        return

    print("\n" + "=" * 60)
    print("  ERROR: Missing required packages")
    print("=" * 60)
    print()
    for _, pip_name in missing:
        print(f"  [MISSING]  {pip_name}")
    print()
    pip_names = " ".join(pip_name for _, pip_name in missing)
    print("  Fix (run this in your terminal, then try again):")
    print()
    print(f"      pip install {pip_names}")
    print()
    print("  Or install all requirements at once:")
    print()
    print("      pip install -r requirements.txt")
    print()
    print("=" * 60)
    sys.exit(1)


# -- File preflight ------------------------------------------------------------

def preflight_check(project_root: Path) -> list[str]:
    """Check that all critical files are present before starting."""
    required = [
        # Classic UI
        "app/ui/index.html",
        "app/ui/style.css",
        # New governed UI (/v2/)
        "app/ui2/index.html",
        "app/ui2/js/app.js",
        "app/ui2/js/primitives.js",
        # API
        "app/api/routes/reader.py",
        "app/core/authoring.py",
        "app/core/execution.py",
        "app/core/ollama.py",
        "app/core/governance.py",
        "app/core/audit.py",
    ]
    return [f for f in required if not (project_root / f).exists()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bag of Holding -- Local Knowledge Workbench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--port",       type=int,  default=DEFAULT_PORT,  help="Port to listen on (default: 8000)")
    p.add_argument("--host",       type=str,  default=DEFAULT_HOST,  help="Host to bind (default: 127.0.0.1)")
    p.add_argument("--library",    type=str,  default=None,          help="Library root path (overrides BOH_LIBRARY env)")
    p.add_argument("--db",         type=str,  default=None,          help="Database file path (overrides BOH_DB env)")
    p.add_argument("--no-browser", action="store_true",              help="Do not open browser automatically")
    p.add_argument("--reload",     action="store_true",              help="Enable uvicorn hot-reload (dev mode)")
    p.add_argument("--no-mcp",     action="store_true",              help="Skip configured MCP connector autostart")
    return p.parse_args(argv)


def wait_for_ready(url: str, timeout: float = MAX_WAIT_S) -> bool:
    """Poll the health endpoint until it responds or timeout expires."""
    try:
        import urllib.request
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(0.3)
        return False
    except Exception:
        return False


def port_is_open(host: str, port: int) -> bool:
    """Return True when something is already listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def main(argv: list[str] | None = None):
    # Step 1: Dependency check (clear error before uvicorn crashes)
    dependency_preflight()

    args = parse_args(argv)

    # Step 2: File preflight
    missing = preflight_check(PROJECT_ROOT)
    if missing:
        print("\nERROR: Missing required files -- wrong directory?")
        for f in missing:
            print(f"  [MISSING]  {f}")
        print(f"\n  Expected to run from: {PROJECT_ROOT}")
        print("  Make sure you are inside the repository root folder.\n")
        sys.exit(1)
    print("[OK] File check passed")

    # Step 3: Build environment
    env = os.environ.copy()
    if args.library:
        env["BOH_LIBRARY"] = str(Path(args.library).resolve())
    if args.db:
        env["BOH_DB"] = str(Path(args.db).resolve())

    os.chdir(PROJECT_ROOT)

    # Auto-find a free port (try up to 10 consecutive ports)
    port = args.port
    if port_is_open(args.host, port):
        print(f"  Port {port} is in use -- scanning for a free port...")
        for candidate in range(port + 1, port + 10):
            if not port_is_open(args.host, candidate):
                print(f"  Using port {candidate} instead.")
                port = candidate
                break
        else:
            print(f"ERROR: Ports {args.port}-{args.port + 9} are all in use on {args.host}.")
            print(f"  Open existing server: http://{args.host}:{args.port}/")
            print("  Or specify a port manually:  python launcher.py --port 9100")
            sys.exit(1)
    base_url   = f"http://{args.host}:{port}"
    health_url = base_url + HEALTH_ENDPOINT

    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.api.main:app",
        "--host", args.host,
        "--port", str(port),
    ]
    if args.reload:
        cmd.append("--reload")

    print("Bag of Holding")
    print(f"  Starting server on {base_url}")
    print(f"  Governed UI: {base_url}/")
    print(f"  Classic UI:  {base_url}/classic  (legacy — rollback only)")
    if env.get("BOH_LIBRARY"):
        print(f"  Library:  {env['BOH_LIBRARY']}")
    print()

    connector_runtime = None

    # Step 4: Start uvicorn subprocess
    try:
        proc = subprocess.Popen(cmd, env=env, cwd=str(PROJECT_ROOT))
    except OSError as exc:
        print(f"ERROR: Python / uvicorn could not start ({type(exc).__name__}).")
        print("  Fix:  pip install uvicorn fastapi")
        sys.exit(1)

    # Step 5: Wait for ready
    print("  Waiting for server...", end="", flush=True)
    time.sleep(STARTUP_WAIT_S)
    ready = wait_for_ready(health_url)
    if ready:
        print(" ready [OK]")
    else:
        rc = proc.poll()
        if rc is not None:
            if connector_runtime is not None:
                connector_runtime.stop()
            print(f"\n\nERROR: Server exited with code {rc} before becoming ready.")
            print("  Check the output above for details.")
            print("  Common causes:")
            print("    - Missing dependency  -> pip install -r requirements.txt")
            print("    - Port already in use -> python launcher.py --port 9000")
            print("    - Wrong directory     -> cd into the repository root folder first")
            sys.exit(rc)
        print(" (timeout -- server may still be starting)")

    # Step 6: Open browser at / (governed UI)
    if not args.no_browser:
        ui_url = base_url + "/"
        print(f"  Opening {ui_url}")
        webbrowser.open(ui_url)

    def shutdown(sig, frame):
        print("\n  Shutting down...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if connector_runtime is not None:
            connector_runtime.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # MCP starts only after Uvicorn is already serving and signal cleanup is
    # installed. Connector readiness can never delay BOH API/UI availability.
    if args.no_mcp:
        print("  MCP connector autostart skipped (--no-mcp)")
    else:
        try:
            from app.core.mcp_connector import start_if_enabled
            connector_runtime = start_if_enabled(PROJECT_ROOT, env=env)
            connector_state = connector_runtime.safe_dict()
            if connector_state["enabled"] and connector_state["error"]:
                print(f"  [WARN] MCP connector: {connector_state['error']} (BOH will continue)")
            elif connector_state["enabled"]:
                mode = "reused" if connector_state["gateway_reused"] and connector_state["tunnel_reused"] else "ready"
                print(f"  MCP connector: {mode} [OK]")
        except Exception as exc:
            print(f"  [WARN] MCP connector: mcp_start_failed:{type(exc).__name__} (BOH will continue)")

    print(f"\n  Press Ctrl+C to stop\n")

    try:
        proc.wait()
    except KeyboardInterrupt:
        shutdown(None, None)

    if connector_runtime is not None:
        connector_runtime.stop()

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

"""launcher.py: Desktop launcher for Bag of Holding v2.

Double-click (or run: python launcher.py) to start the server and open the browser.
No uvicorn command knowledge required.

Usage:
    python launcher.py                  # default port 8000
    python launcher.py --port 9000      # custom port
    python launcher.py --no-browser     # headless / server-only
    python launcher.py --library /path  # set library root at launch
"""

import argparse
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_PORT    = 8000
DEFAULT_HOST    = "127.0.0.1"
STARTUP_WAIT_S  = 2.5      # seconds to wait before polling health
MAX_WAIT_S      = 14.0     # max wait before giving up on health check
HEALTH_ENDPOINT = "/api/health"

# ── Resolve project root ───────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()


# ── Dependency check (runs before uvicorn so crash is readable) ───────────────
REQUIRED_PACKAGES = {
    # import-name : pip install name
    "fastapi":          "fastapi",
    "uvicorn":          "uvicorn",
    "pydantic":         "pydantic",
    "yaml":             "PyYAML",
    "multipart":        "python-multipart",
    "starlette":        "starlette",
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
    """Check all required packages are installed. Print clear fix instructions and exit if not."""
    missing = check_dependencies()
    if not missing:
        return

    print("\n" + "=" * 60)
    print("  ERROR: Missing required packages")
    print("=" * 60)
    print()
    for _, pip_name in missing:
        print(f"  ✗  {pip_name}")
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


# ── File preflight ────────────────────────────────────────────────────────────

def preflight_check(project_root: Path) -> list[str]:
    """Check that all critical Phase 11 files are present before starting."""
    required = [
        "app/ui/index.html",
        "app/ui/app.js",
        "app/ui/style.css",
        "app/ui/vendor/katex.min.js",
        "app/ui/vendor/marked.min.js",
        "app/api/routes/reader.py",
        "app/core/related.py",
        "app/core/daenary.py",
        "app/core/dcns.py",
        "app/core/authoring.py",
        "app/core/execution.py",
        "app/core/ollama.py",
        "app/core/governance.py",
        "app/core/audit.py",
        "app/core/input_surface.py",
        "app/api/routes/input_routes.py",
    ]
    return [f for f in required if not (project_root / f).exists()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bag of Holding v2 — Local Knowledge Workbench Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--port",       type=int,  default=DEFAULT_PORT)
    p.add_argument("--host",       type=str,  default=DEFAULT_HOST)
    p.add_argument("--library",    type=str,  default=None)
    p.add_argument("--db",         type=str,  default=None)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--reload",     action="store_true")
    return p.parse_args()


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


def main():
    # ── Step 1: Dependency check (clear error before uvicorn crashes) ──────────
    dependency_preflight()

    args = parse_args()

    # ── Step 2: File preflight ─────────────────────────────────────────────────
    missing = preflight_check(PROJECT_ROOT)
    if missing:
        print("\nERROR: Missing Phase 11 files — wrong directory?")
        for f in missing:
            print(f"  ✗  {f}")
        print(f"\n  Expected to run from: {PROJECT_ROOT}")
        print("  Make sure you are inside the boh_p11/ folder.\n")
        sys.exit(1)
    print("✓  Phase 11 file check passed")

    # ── Step 3: Build environment ──────────────────────────────────────────────
    env = os.environ.copy()
    if args.library:
        env["BOH_LIBRARY"] = str(Path(args.library).resolve())
    if args.db:
        env["BOH_DB"] = str(Path(args.db).resolve())

    os.chdir(PROJECT_ROOT)

    base_url   = f"http://{args.host}:{args.port}"
    health_url = base_url + HEALTH_ENDPOINT

    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.api.main:app",
        "--host", args.host,
        "--port", str(args.port),
    ]
    if args.reload:
        cmd.append("--reload")

    print(f"📦 Bag of Holding v2")
    print(f"   Starting server on {base_url}")
    if env.get("BOH_LIBRARY"):
        print(f"   Library: {env['BOH_LIBRARY']}")
    print()

    # ── Step 4: Start uvicorn subprocess ───────────────────────────────────────
    try:
        proc = subprocess.Popen(cmd, env=env, cwd=str(PROJECT_ROOT))
    except FileNotFoundError:
        print("ERROR: Python / uvicorn not found.")
        print("  Fix:  pip install uvicorn fastapi")
        sys.exit(1)

    # ── Step 5: Wait for ready ─────────────────────────────────────────────────
    print("   Waiting for server…", end="", flush=True)
    time.sleep(STARTUP_WAIT_S)
    ready = wait_for_ready(health_url)
    if ready:
        print(" ready ✓")
    else:
        # Check if the subprocess already died (means startup crashed)
        rc = proc.poll()
        if rc is not None:
            print(f"\n\nERROR: Server exited with code {rc} before becoming ready.")
            print("  Check the output above for details.")
            print("  Common causes:")
            print("    • Missing dependency  → pip install -r requirements.txt")
            print("    • Port already in use → python launcher.py --port 9000")
            print("    • Wrong directory     → cd into the boh_p11/ folder first")
            sys.exit(rc)
        print(" (timeout — server may still be starting)")

    # ── Step 6: Open browser ───────────────────────────────────────────────────
    if not args.no_browser:
        print(f"   Opening {base_url}")
        webbrowser.open(base_url)

    print(f"\n   Press Ctrl+C to stop\n")

    def shutdown(sig, frame):
        print("\n   Shutting down…")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        proc.wait()
    except KeyboardInterrupt:
        shutdown(None, None)

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())


# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_PORT    = 8000
DEFAULT_HOST    = "127.0.0.1"
STARTUP_WAIT_S  = 2.0      # seconds to wait for uvicorn to be ready
MAX_WAIT_S      = 10.0     # max wait before giving up on health check
HEALTH_ENDPOINT = "/api/health"

# ── Resolve project root ───────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bag of Holding v2 — Local Knowledge Workbench Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--port",       type=int,  default=DEFAULT_PORT, help="Port to listen on (default: 8000)")
    p.add_argument("--host",       type=str,  default=DEFAULT_HOST, help="Host to bind (default: 127.0.0.1)")
    p.add_argument("--library",    type=str,  default=None,         help="Library root path (overrides BOH_LIBRARY env)")
    p.add_argument("--db",         type=str,  default=None,         help="Database file path (overrides BOH_DB env)")
    p.add_argument("--no-browser", action="store_true",             help="Do not open browser automatically")
    p.add_argument("--reload",     action="store_true",             help="Enable uvicorn hot-reload (dev mode)")
    return p.parse_args()


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
            time.sleep(0.25)
        return False
    except Exception:
        return False


def preflight_check(project_root: Path) -> list[str]:
    """Check that all critical Phase 10 files are present before starting."""
    required = [
        "app/ui/index.html",
        "app/ui/app.js",
        "app/ui/style.css",
        "app/ui/vendor/katex.min.js",
        "app/ui/vendor/marked.min.js",
        "app/api/routes/reader.py",
        "app/core/related.py",
        "app/core/daenary.py",
        "app/core/dcns.py",
        "app/core/authoring.py",
        "app/core/execution.py",
        "app/core/ollama.py",
        "app/core/governance.py",
        "app/core/audit.py",
    ]
    missing = [f for f in required if not (project_root / f).exists()]
    return missing


def main():
    args = parse_args()

    # ── Pre-flight: verify Phase 7 files are present ──────────────────────────
    missing = preflight_check(PROJECT_ROOT)
    if missing:
        print("ERROR: Missing Phase 10 files — wrong directory?")
        for f in missing:
            print(f"  ✗  {f}")
        print(f"\n  Expected to run from: {PROJECT_ROOT}")
        print("  Make sure you're inside the boh_v2/ folder from the Phase 10 zip.\n")
        sys.exit(1)
    print("✓  Phase 10 file check passed")

    # Build environment
    env = os.environ.copy()
    if args.library:
        env["BOH_LIBRARY"] = str(Path(args.library).resolve())
    if args.db:
        env["BOH_DB"] = str(Path(args.db).resolve())

    # Ensure we run from project root so relative paths work
    os.chdir(PROJECT_ROOT)

    base_url = f"http://{args.host}:{args.port}"
    health_url = base_url + HEALTH_ENDPOINT

    # Build uvicorn command
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.api.main:app",
        "--host", args.host,
        "--port", str(args.port),
    ]
    if args.reload:
        cmd.append("--reload")

    print(f"📦 Bag of Holding v2")
    print(f"   Starting server on {base_url}")
    if env.get("BOH_LIBRARY"):
        print(f"   Library: {env['BOH_LIBRARY']}")
    if env.get("BOH_DB"):
        print(f"   Database: {env['BOH_DB']}")
    print()

    # Start uvicorn subprocess
    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=str(PROJECT_ROOT),
        )
    except FileNotFoundError:
        print("ERROR: Python / uvicorn not found. Run: pip install uvicorn fastapi")
        sys.exit(1)

    # Wait for server to be ready
    print("   Waiting for server…", end="", flush=True)
    time.sleep(STARTUP_WAIT_S)
    ready = wait_for_ready(health_url)
    if ready:
        print(" ready ✓")
    else:
        print(" (timeout — server may still be starting)")

    # Open browser
    if not args.no_browser:
        print(f"   Opening {base_url}")
        webbrowser.open(base_url)

    print(f"\n   Press Ctrl+C to stop\n")

    # Forward signals to child process for clean shutdown
    def shutdown(sig, frame):
        print("\n   Shutting down…")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Wait for child to exit
    try:
        proc.wait()
    except KeyboardInterrupt:
        shutdown(None, None)

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

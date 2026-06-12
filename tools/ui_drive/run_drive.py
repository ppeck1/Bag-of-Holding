"""tools/ui_drive/run_drive.py — one-command full-UI demo + headless frontend drive.

Spins up a throwaway server on a free port against a TEMP database + library (your real
boh.db is never touched), seeds it with the full demo data, drives the real /v2 UI through
the Node DOM harness, prints the PASS/FAIL report, and tears everything down.

Usage (from the repo root):
    python tools/ui_drive/run_drive.py
    python tools/ui_drive/run_drive.py --keep      # leave the server running afterwards
    python tools/ui_drive/run_drive.py --port 8155 # pin the port

Exit code 0 iff every drive check passes. Requires `node` on PATH (skips the drive with a
clear message otherwise). Safe to run repeatedly; nothing in your working tree changes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DRIVE = Path(__file__).resolve().parent


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait_health(base: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Full-UI demo + headless frontend drive.")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--keep", action="store_true", help="leave the server running")
    args = ap.parse_args()

    node = shutil.which("node")
    if not node:
        print("node not found on PATH — the headless drive needs Node. "
              "Install Node or run the Python suite instead (pytest tests -q).")
        return 2

    port = args.port or _free_port()
    base = f"http://127.0.0.1:{port}"
    workdir = Path(tempfile.mkdtemp(prefix="boh_uidrive_"))
    (workdir / "library").mkdir()

    env = dict(os.environ)
    env["BOH_DB"] = str(workdir / "boh.db")
    env["BOH_LIBRARY"] = str(workdir / "library")
    env["BOH_DATA_ROOT"] = str(workdir)
    env.setdefault("BOH_OPERATOR_TOKEN", "uidrive-token")
    # Seeds/launcher print Unicode (arrows); force UTF-8 so captured stdout on Windows
    # (cp1252) does not crash the child process.
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"Temp workspace: {workdir}")
    print(f"Starting server on {base} (throwaway DB/library) ...")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    rc = 1
    try:
        if not _wait_health(base):
            print("Server did not become healthy in time.")
            return 1

        print("Seeding demo data ...")
        for script in ("seed_ui_demo.py",):
            p = subprocess.run([sys.executable, script], cwd=str(REPO), env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            tail = (p.stdout or p.stderr).strip().splitlines()[-1:] or [""]
            print(f"  {script}: {tail[0]}")
            if p.returncode != 0:
                print(p.stderr[-500:])
                return 1

        print("Driving the /v2 frontend (real modules, real fetch) ...\n")
        drive = subprocess.run(
            [node, str(DRIVE / "drive_all.mjs")],
            cwd=str(DRIVE), env={**env, "BOH_BASE": base},
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        sys.stdout.buffer.write(drive.stdout.encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
        if drive.stderr.strip():
            sys.stdout.buffer.write(("\n[stderr]\n" + drive.stderr[-800:]).encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        rc = 0 if (drive.returncode == 0 and "FAILURES" not in drive.stdout) else 1
        return rc
    finally:
        if args.keep:
            print(f"\n--keep: server still running at {base} (pid {server.pid}); "
                  f"temp workspace {workdir} retained. Stop it manually when done.")
        else:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:
                server.kill()
            shutil.rmtree(workdir, ignore_errors=True)
            print(f"\nTorn down. {'PASS' if rc == 0 else 'FAIL'}")


if __name__ == "__main__":
    raise SystemExit(main())

"""tests/test_phase5.py: Phase 5 tests — launcher and health endpoint.

Tests the /api/health endpoint (launcher prerequisite) and launcher module
can be imported and parsed without errors. Does not start a live subprocess.
"""

import os
import importlib
import pytest

os.environ.setdefault("BOH_DB", os.path.join(os.path.dirname(__file__), "test_boh_v2.db"))
os.environ.setdefault("BOH_LIBRARY", os.path.join(os.path.dirname(__file__), "..", "library"))

from fastapi.testclient import TestClient
from app.api.main import app
from app.db import connection as db

client = TestClient(app)


@pytest.fixture(autouse=True, scope="module")
def init():
    db.init_db()


# ── Health endpoint ───────────────────────────────────────────────────────────

def test_health_returns_200():
    r = client.get("/api/health")
    assert r.status_code == 200


def test_health_body_structure():
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["version"] == "2.0.0"
    assert body["db"] == "connected"
    assert "library" in body


def test_health_version_is_v2():
    assert client.get("/api/health").json()["version"] == "2.0.0"


# ── Launcher module ───────────────────────────────────────────────────────────

def test_launcher_module_importable():
    """launcher.py must be importable without side effects."""
    import importlib.util, sys
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "launcher",
        Path(__file__).parent.parent / "launcher.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "main")
    assert hasattr(mod, "parse_args")
    assert hasattr(mod, "wait_for_ready")


def test_launcher_shell_script_exists():
    from pathlib import Path
    assert (Path(__file__).parent.parent / "launcher.sh").exists()


def test_launcher_bat_exists():
    from pathlib import Path
    assert (Path(__file__).parent.parent / "launcher.bat").exists()


def test_pyinstaller_spec_exists():
    from pathlib import Path
    assert (Path(__file__).parent.parent / "boh.spec").exists()


# ── StaticFiles serving ───────────────────────────────────────────────────────

def test_ui_html_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Bag of Holding" in r.text


def test_ui_css_served():
    r = client.get("/style.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "")


def test_ui_js_served():
    r = client.get("/app.js")
    assert r.status_code == 200


def test_swagger_docs_served():
    r = client.get("/docs")
    assert r.status_code == 200


# ── All API routes reachable (smoke) ─────────────────────────────────────────

ROUTES_GET = [
    "/api/health",
    "/api/dashboard",
    "/api/docs",
    "/api/conflicts",
    "/api/workflow",
    "/api/events",
    "/api/events/export.ics",
    "/api/planes",
    "/api/lineage",
    "/api/duplicates",
    "/api/corpus/classes",
    "/api/corpus/migration-report",
]

@pytest.mark.parametrize("path", ROUTES_GET)
def test_all_get_routes_return_200(path):
    r = client.get(path)
    assert r.status_code == 200, f"GET {path} returned {r.status_code}"

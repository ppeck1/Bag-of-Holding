"""tests/test_route_authority_policy.py — Route authority classification policy.

Enumerates every non-GET route in the app and asserts that each is either:
  (A) guarded by require_operator or require_retrieval_token, OR
  (B) listed in INTENTIONALLY_OPEN with a documented classification and reason.

This test prevents new side-effectful routes from bypassing classification.
If a new mutation route is added without a guard, this test will fail.

Classification values (documented in route_authority_todo_audit.md):
  truly-read-only          — POST but no state change (advisory, inference, lookup)
  separate-boundary        — uses its own token boundary (retrieval token)
  intentionally-dead       — raises 410; never executes mutation logic
  expensive-execution      — guarded by operator token (e.g. ollama invoke)
  governed-state           — guarded by operator token
  filesystem-external      — guarded by operator token
"""

from __future__ import annotations

import importlib
from fastapi import FastAPI
from fastapi.routing import APIRoute

# ---------------------------------------------------------------------------
# Intentionally open routes — POST/PATCH/PUT/DELETE without operator guard.
# Each entry documents WHY the route is intentionally open.
# Adding a new entry here requires a code review per the repo's governed-change contract.
# ---------------------------------------------------------------------------

INTENTIONALLY_OPEN: dict[str, dict] = {
    # approval_routes.py — dead legacy paths
    "POST /api/governance/approve/request-promotion": {
        "classification": "intentionally-dead",
        "reason": "Raises HTTP 410. Phase 20.1 removed direct promotion. Use certificate flow.",
    },
    # certificate_routes.py — dead legacy paths
    "POST /api/promote": {
        "classification": "intentionally-dead",
        "reason": "Raises HTTP 410. Phase 20.1 removed direct promotion.",
    },
    "POST /api/node/promote": {
        "classification": "intentionally-dead",
        "reason": "Raises HTTP 410. Phase 20.1 removed direct node promotion.",
    },
    "POST /api/canonicalize": {
        "classification": "intentionally-dead",
        "reason": "Raises HTTP 410. Phase 20.1 removed direct canonicalization.",
    },
    # authority_routes.py — advisory/inference endpoints
    "POST /api/authority/validate": {
        "classification": "truly-read-only",
        "reason": "Advisory auth check; calls validate_resolution_authority(); no DB writes.",
    },
    "POST /api/authority/explain": {
        "classification": "truly-read-only",
        "reason": "Translates a blocked-result dict to legible explanation; no DB writes.",
    },
    "POST /api/authority/sc3/check": {
        "classification": "truly-read-only",
        "reason": "Returns constitutive/descriptive classification; calls sc3_constitutive_check(); no writes.",
    },
    "POST /api/authority/sc3/promotion-gate": {
        "classification": "truly-read-only",
        "reason": "_ensure_sc3_violations_table() is idempotent DDL only; sc3_promotion_gate() verified no DB writes.",
    },
    "POST /api/authority/sc3/infer-plane": {
        "classification": "truly-read-only",
        "reason": "Metadata-only plane inference; no DB writes.",
    },
    "POST /api/authority/translation/label": {
        "classification": "truly-read-only",
        "reason": "Label translation lookup; no DB writes.",
    },
    "POST /api/authority/translation/status": {
        "classification": "truly-read-only",
        "reason": "Status translation lookup; no DB writes.",
    },
    "POST /api/authority/translation/mode": {
        "classification": "truly-read-only",
        "reason": "Mode translation lookup; no DB writes.",
    },
    # context_pack_routes.py — explicitly documented read-only
    "POST /api/context-pack/assemble": {
        "classification": "truly-read-only",
        "reason": "Docstring: 'Read-only: it assembles a SUPPLIED candidate-pack list. Performs no DB writes.'",
    },
    # feedback_routes.py — preview endpoint
    "POST /api/feedback/preview": {
        "classification": "truly-read-only",
        "reason": "Docstring: 'This endpoint is read-only. It never writes to the database.'",
    },
    # retrieval_routes.py — separate token boundary
    "POST /api/retrieve": {
        "classification": "separate-boundary",
        "reason": "Uses BOH_RETRIEVAL_TOKEN (require_retrieval_token); intentionally separate from operator boundary.",
    },
    # substrate_routes.py — validation test
    "POST /api/substrate/validate": {
        "classification": "truly-read-only",
        "reason": "Runs run_validation_test(); Fix H anti-bullshit check; no DB writes.",
    },
}

GUARDED_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def _get_app() -> FastAPI:
    import app.api.main as main
    importlib.reload(main)
    return main.app


def _dep_name(fn) -> str:
    """Return a reload-stable identity for a dependency callable.

    Object identity (``is``) is unreliable because ~34 test files call
    importlib.reload on app.core.auth / app.api.main, after which the function
    object bound in a route is a different object than a freshly-imported one.
    Comparing by module + qualified name is stable across reloads.
    """
    mod = getattr(fn, "__module__", "") or ""
    qn = getattr(fn, "__qualname__", getattr(fn, "__name__", "")) or ""
    return f"{mod}.{qn}"


def _route_has_named_guard(route: APIRoute, guard_names: set[str]) -> bool:
    """True if any of the route's dependencies matches one of guard_names by name."""
    # FastAPI flattens declared dependencies into route.dependant.dependencies.
    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        stack = list(getattr(dependant, "dependencies", []))
        while stack:
            sub = stack.pop()
            call = getattr(sub, "call", None)
            if call is not None and _dep_name(call) in guard_names:
                return True
            stack.extend(getattr(sub, "dependencies", []))
    # Fallback: inspect endpoint signature defaults (Depends(...) markers).
    import inspect
    try:
        sig = inspect.signature(route.endpoint)
    except (TypeError, ValueError):
        return False
    for param in sig.parameters.values():
        dep = getattr(param.default, "dependency", None)
        if dep is not None and _dep_name(dep) in guard_names:
            return True
    return False


_OPERATOR_GUARD_NAMES = {"app.core.auth.require_operator"}
_RETRIEVAL_GUARD_NAMES = {"app.core.retrieval.require_retrieval_token"}


def _route_has_operator_guard(route: APIRoute) -> bool:
    return _route_has_named_guard(route, _OPERATOR_GUARD_NAMES)


def _route_has_retrieval_guard(route: APIRoute) -> bool:
    return _route_has_named_guard(route, _RETRIEVAL_GUARD_NAMES)


class TestRouteAuthorityPolicy:
    def test_all_mutation_routes_classified(self, tmp_path, monkeypatch):
        """Every POST/PATCH/PUT/DELETE route must be guarded or in INTENTIONALLY_OPEN."""
        import app.db.connection as db_conn
        db_path = tmp_path / "boh.db"
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path / "library"))
        monkeypatch.setenv("BOH_DB", str(db_path))
        monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")
        (tmp_path / "library").mkdir()
        db_conn.DB_PATH = str(db_path)
        db_conn.init_db()

        app = _get_app()
        unclassified = []

        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods or []:
                if method.upper() not in GUARDED_METHODS:
                    continue
                route_key = f"{method.upper()} {route.path}"
                if route_key in INTENTIONALLY_OPEN:
                    continue
                if _route_has_operator_guard(route):
                    continue
                if _route_has_retrieval_guard(route):
                    continue
                unclassified.append(route_key)

        assert not unclassified, (
            f"The following mutation routes are neither guarded nor in INTENTIONALLY_OPEN.\n"
            f"Either add Depends(require_operator) or add an entry to INTENTIONALLY_OPEN "
            f"with a documented classification and reason.\n\n"
            + "\n".join(f"  {r}" for r in sorted(unclassified))
        )

    def test_intentionally_open_entries_have_required_fields(self):
        """Every INTENTIONALLY_OPEN entry must have classification and reason."""
        for route_key, meta in INTENTIONALLY_OPEN.items():
            assert "classification" in meta, f"{route_key}: missing 'classification'"
            assert "reason" in meta, f"{route_key}: missing 'reason'"
            assert meta["classification"] in {
                "truly-read-only", "separate-boundary",
                "intentionally-dead", "expensive-execution",
                "governed-state", "filesystem-external",
            }, f"{route_key}: unknown classification '{meta['classification']}'"

    def test_ollama_invoke_guarded(self, tmp_path, monkeypatch):
        """POST /api/ollama/invoke must require operator token."""
        import app.db.connection as db_conn
        db_path = tmp_path / "boh.db"
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path / "library"))
        monkeypatch.setenv("BOH_DB", str(db_path))
        monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")
        (tmp_path / "library").mkdir()
        db_conn.DB_PATH = str(db_path)
        db_conn.init_db()
        from fastapi.testclient import TestClient
        app = _get_app()
        with TestClient(app) as client:
            r = client.post("/api/ollama/invoke", json={
                "task_type": "summarize", "content": "hello", "doc_id": "test"
            })
            assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_substrate_register_guarded(self, tmp_path, monkeypatch):
        """POST /api/substrate/register must require operator token."""
        import app.db.connection as db_conn
        db_path = tmp_path / "boh.db"
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path / "library"))
        monkeypatch.setenv("BOH_DB", str(db_path))
        monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")
        (tmp_path / "library").mkdir()
        db_conn.DB_PATH = str(db_path)
        db_conn.init_db()
        from fastapi.testclient import TestClient
        app = _get_app()
        with TestClient(app) as client:
            r = client.post("/api/substrate/register", json={
                "domain": "test", "label": "test", "k_physical": "a",
                "k_informational": "b", "k_subjective": "c",
                "x_physical": "d", "x_informational": "e", "x_subjective": "f",
                "f_physical": "g", "f_informational": "h", "f_subjective": "i",
            })
            assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_upload_already_guarded(self, tmp_path, monkeypatch):
        """POST /api/input/upload must require operator token (regression guard)."""
        import app.db.connection as db_conn
        db_path = tmp_path / "boh.db"
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path / "library"))
        monkeypatch.setenv("BOH_DB", str(db_path))
        monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")
        (tmp_path / "library").mkdir()
        db_conn.DB_PATH = str(db_path)
        db_conn.init_db()
        from fastapi.testclient import TestClient
        import io
        app = _get_app()
        with TestClient(app) as client:
            r = client.post("/api/input/upload",
                files={"files": ("test.md", io.BytesIO(b"# Test"), "text/markdown")})
            assert r.status_code == 401, f"Expected 401, got {r.status_code}"

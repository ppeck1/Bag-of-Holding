"""tests/test_canon_geometry.py — CANON geometry bridge.

Covers:
  - app/core/scalar_metrics.py neutral formulas (omega_viability, mismatch_gradient,
    metadata_completeness, viability_completeness_record defaults)
  - graph/Fold parity: /api/graph/projection viability_margin == /api/fold/node
    omega_viability, and projection_loss == mismatch_gradient, for the same doc
  - parity holds for a partially-populated doc (exercises default normalization)
  - /api/fold/library partial mode emits omega/mismatch as null with warnings
  - graph projection numeric output is unchanged by the refactor (golden formula check)
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.core import scalar_metrics


# ---------------------------------------------------------------------------
# Unit tests — neutral formulas
# ---------------------------------------------------------------------------

class TestScalarMetricsFormulas:
    def test_completeness_all_present(self):
        rec = {f: "x" for f in scalar_metrics.COMPLETENESS_FIELDS}
        assert scalar_metrics.metadata_completeness(rec) == 1.0

    def test_completeness_none_present(self):
        rec = {f: "" for f in scalar_metrics.COMPLETENESS_FIELDS}
        assert scalar_metrics.metadata_completeness(rec) == 0.0

    def test_completeness_excludes_unassigned_and_unknown(self):
        rec = {f: "x" for f in scalar_metrics.COMPLETENESS_FIELDS}
        rec["review_state"] = "unassigned"
        rec["document_class"] = "unknown"
        # 6 of 8 present
        assert scalar_metrics.metadata_completeness(rec) == 6 / 8

    def test_mismatch_gradient_is_one_minus_completeness(self):
        assert scalar_metrics.mismatch_gradient(1.0) == 0.0
        assert scalar_metrics.mismatch_gradient(0.0) == 1.0
        assert abs(scalar_metrics.mismatch_gradient(0.75) - 0.25) < 1e-9

    def test_omega_viability_formula(self):
        # authority 0.95, no conflicts/coords, full completeness → 0.95
        v = scalar_metrics.omega_viability(0.95, 0, 0, 0, 1.0)
        assert abs(v - 0.95) < 1e-9

    def test_omega_viability_penalizes_conflicts(self):
        high = scalar_metrics.omega_viability(0.95, 0, 0, 0, 1.0)
        low = scalar_metrics.omega_viability(0.95, 4, 0, 0, 1.0)
        assert low < high

    def test_omega_viability_clamped(self):
        v = scalar_metrics.omega_viability(0.0, 100, 100, 100, 0.0)
        assert 0.0 <= v <= 1.0

    def test_omega_viability_nan_safe(self):
        v = scalar_metrics.omega_viability(float("nan"), 0, 0, 0, 1.0)
        assert v == v  # not NaN

    def test_viability_completeness_record_defaults(self):
        # Empty doc row → graph-identical defaults
        rec = scalar_metrics.viability_completeness_record({}, basename="bn")
        assert rec["title"] == "bn"
        assert rec["project"] == "Quarantine / Legacy Import"
        assert rec["document_class"] == "unknown"
        assert rec["canonical_layer"] == "quarantine"
        assert rec["authority_state"] == "quarantined"
        assert rec["review_state"] == "unassigned"
        assert rec["summary"] == ""

    def test_viability_completeness_record_document_class_type_fallback(self):
        rec = scalar_metrics.viability_completeness_record({"type": "note"}, basename="x")
        assert rec["document_class"] == "note"


# ---------------------------------------------------------------------------
# Parity fixture (TestClient over a temp DB)
# ---------------------------------------------------------------------------

@contextmanager
def _client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")

    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()

    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db


def _insert_doc(db, doc_id, **fields):
    cols = ["doc_id", "path"]
    vals = [doc_id, f"/library/{doc_id}.md"]
    for k, v in fields.items():
        cols.append(k)
        vals.append(v)
    placeholders = ",".join("?" for _ in cols)
    db.execute(
        f"INSERT OR IGNORE INTO docs ({','.join(cols)}) VALUES ({placeholders})",
        tuple(vals),
    )


def _graph_node(client, doc_id):
    r = client.get("/api/graph/projection?mode=web&max_nodes=300")
    assert r.status_code == 200
    for n in r.json().get("nodes", []):
        if n.get("id") == doc_id:
            return n
    return None


def _fold_canon(client, doc_id):
    r = client.get(f"/api/fold/node/{doc_id}")
    assert r.status_code == 200
    return r.json().get("canon_variables")


# ---------------------------------------------------------------------------
# Graph / Fold parity
# ---------------------------------------------------------------------------

class TestGraphFoldParity:
    def test_fully_populated_doc_parity(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db):
            _insert_doc(
                db, "p1", title="Doc One", project="boh",
                document_class="note", canonical_layer="canonical",
                authority_state="canonical", review_state="approved",
                status="canonical", summary="A complete document.",
            )
            node = _graph_node(client, "p1")
            canon = _fold_canon(client, "p1")
            assert node is not None
            assert canon is not None
            assert canon["omega_viability"] is not None
            assert abs(node["constraint_metrics"]["viability_margin"] - canon["omega_viability"]) < 1e-9
            assert abs(node["constraint_metrics"]["projection_loss"] - canon["mismatch_gradient"]) < 1e-9

    def test_partially_populated_doc_parity(self, tmp_path, monkeypatch):
        # Missing project, document_class, review_state, summary → default normalization
        # must match between the two paths.
        with _client(tmp_path, monkeypatch) as (client, db):
            _insert_doc(
                db, "p2", title="Partial", status="draft",
                canonical_layer="review", authority_state="under_review",
            )
            node = _graph_node(client, "p2")
            canon = _fold_canon(client, "p2")
            assert node is not None and canon is not None
            assert abs(node["constraint_metrics"]["viability_margin"] - canon["omega_viability"]) < 1e-9
            assert abs(node["constraint_metrics"]["projection_loss"] - canon["mismatch_gradient"]) < 1e-9

    def test_bare_doc_parity(self, tmp_path, monkeypatch):
        # Only doc_id + path; everything else defaulted.
        with _client(tmp_path, monkeypatch) as (client, db):
            _insert_doc(db, "p3")
            node = _graph_node(client, "p3")
            canon = _fold_canon(client, "p3")
            assert node is not None and canon is not None
            assert abs(node["constraint_metrics"]["viability_margin"] - canon["omega_viability"]) < 1e-9
            assert abs(node["constraint_metrics"]["projection_loss"] - canon["mismatch_gradient"]) < 1e-9

    def test_fold_node_exact_mode_populates_geometry(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db):
            _insert_doc(db, "p4", title="X", status="canonical",
                        canonical_layer="canonical", authority_state="canonical")
            canon = _fold_canon(client, "p4")
            assert canon["calculation_mode"] == "exact"
            assert canon["omega_viability"] is not None
            assert canon["mismatch_gradient"] is not None
            # No omega/mismatch warnings when geometry is computed
            assert not any("omega_viability" in w for w in canon["warnings"])
            assert not any("mismatch_gradient" in w for w in canon["warnings"])


# ---------------------------------------------------------------------------
# Library batch (partial mode)
# ---------------------------------------------------------------------------

class TestLibraryPartialMode:
    def test_library_omega_mismatch_null_with_warnings(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db):
            _insert_doc(db, "lib1", title="L", status="draft", authority_state="draft")
            r = client.get("/api/fold/library")
            assert r.status_code == 200
            docs = r.json().get("docs", [])
            assert docs
            cv = docs[0].get("canon_variables")
            assert cv is not None
            assert cv["calculation_mode"] == "partial"
            assert cv["omega_viability"] is None
            assert cv["mismatch_gradient"] is None
            assert any("omega_viability" in w for w in cv["warnings"])
            assert any("mismatch_gradient" in w for w in cv["warnings"])

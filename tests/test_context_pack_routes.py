"""Phase 7 Context Pack Builder surface tests (TASK 3.4).

Verifies the read-only /api/context-pack/assemble route that exposes the Phase 6
assembler over a supplied candidate-pack list:
- assembles supplied packs into the five labeled sections + posture
- gate is authoritative: a blocked posture yields empty content (no bypass)
- deterministic: identical requests yield an equal body + assembled_pack_id
- read-only / no canon grant: no DB writes, never exposes canon_eligible=True
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def cp_client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))

    import app.db.connection as db_conn
    db_conn.DB_PATH = str(db_path)
    db_conn.init_db()

    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()

    with TestClient(main.app) as client:
        yield client, db_conn


def _pack(ref="card-1", plane="canonical", **overrides):
    pack = {
        "card_id": ref,
        "doc_id": f"doc-{ref}",
        "title": ref,
        "snippet": f"text for {ref}",
        "path": f"library/{ref}.md",
        "plane": plane,
        "authority_state": "approved",
        "source_trust": "local",
        "scalar_basis_ref": "sb-1",
        "why_selected": {"semantic_score": 0.9},
    }
    pack.update(overrides)
    return pack


def _body(packs, *, operation="answer_context", actor="reader", mode="exploration"):
    return {"query": "q", "operation": operation, "actor": actor, "mode": mode,
            "candidate_packs": packs}


# ---------------------------------------------------------------------------
# Acceptance #1 -- assembles supplied packs
# ---------------------------------------------------------------------------

def test_section_labels_endpoint(cp_client):
    client, _ = cp_client
    labels = client.get("/api/context-pack/section-labels").json()["section_labels"]
    assert labels == ["canon", "evidence", "interpretation", "conflict", "open_questions"]


def test_assemble_places_packs_in_sections(cp_client):
    client, _ = cp_client
    resp = client.post("/api/context-pack/assemble",
                       json=_body([_pack(ref="c", plane="canonical"),
                                   _pack(ref="e", plane="evidence")]))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["sections"].keys()) == {"canon", "evidence", "interpretation", "conflict", "open_questions"}
    assert [e["ref"] for e in data["sections"]["canon"]] == ["c"]
    assert [e["ref"] for e in data["sections"]["evidence"]] == ["e"]
    assert "c" in data["source_map"]
    assert "withheld" in data


# ---------------------------------------------------------------------------
# Acceptance #2 -- gate authoritative / no bypass
# ---------------------------------------------------------------------------

def test_blocked_posture_yields_empty_content(cp_client):
    client, _ = cp_client
    resp = client.post("/api/context-pack/assemble",
                       json=_body([_pack()], operation="promote", actor="reader", mode="strict"))
    data = resp.json()
    assert data["posture"] == "blocked"
    assert all(data["sections"][label] == [] for label in data["sections"])
    assert data["source_map"] == {}
    assert data["withheld"]["reasons"]


# ---------------------------------------------------------------------------
# Acceptance #3 -- deterministic
# ---------------------------------------------------------------------------

def test_assemble_is_deterministic(cp_client):
    client, _ = cp_client
    body = _body([_pack(ref="c", plane="canonical"), _pack(ref="e", plane="evidence")])
    a = client.post("/api/context-pack/assemble", json=body).json()
    b = client.post("/api/context-pack/assemble", json=body).json()
    assert a == b
    assert a["assembled_pack_id"] == b["assembled_pack_id"]


# ---------------------------------------------------------------------------
# Acceptance #4 -- read-only / no canon grant
# ---------------------------------------------------------------------------

def test_assemble_performs_no_db_writes(cp_client, monkeypatch):
    client, db_conn = cp_client

    def _boom(*a, **k):
        raise AssertionError("context pack builder must not execute writes")

    monkeypatch.setattr(db_conn, "execute", _boom, raising=False)
    monkeypatch.setattr(db_conn, "executemany", _boom, raising=False)
    resp = client.post("/api/context-pack/assemble", json=_body([_pack()]))
    assert resp.status_code == 200


def test_canon_eligible_never_true(cp_client):
    client, _ = cp_client
    data = client.post("/api/context-pack/assemble", json=_body([_pack()])).json()
    assert data["canon_eligible"] is False

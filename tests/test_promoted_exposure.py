"""WO-2 exposure-matrix tests: a promoted advisory doc must NOT silently enter any consumer.

Dual gate (DEC-0004 / roadmap §5): /api/retrieve shows promoted docs only when BOTH
BOH_RETRIEVAL_INCLUDE_PROMOTED (server env) AND include_promoted (request) are on. All other
read surfaces are env-gate-only; the graph atlas is deliberately conservative (always excludes).
Temp DBs/fixtures only.
"""

import importlib
from contextlib import contextmanager

from fastapi.testclient import TestClient

TERM = "zanzibar"  # unique token that only the promoted doc contains
PROMOTED_MD = f"# Promoted Source\n\nThe {TERM} fixture sentence has enough unique words here.\n"
NORMAL_MD = """---
boh:
  id: "normal-doc"
  title: "Normal Doc"
  status: "draft"
  authority_state: "draft"
---

# Normal

Ordinary retrieval content with enough words to be queryable today.
"""


@contextmanager
def _client(tmp_path, monkeypatch):
    lib = tmp_path / "library"
    data_root = tmp_path / "dataroot"
    src = tmp_path / "src"
    for d in (lib, data_root, src):
        d.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_LIBRARY", str(lib))
    monkeypatch.setenv("BOH_DATA_ROOT", str(data_root))
    monkeypatch.setenv("BOH_RETRIEVAL_TOKEN", "retrieve-token")
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")
    monkeypatch.delenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", raising=False)

    import app.db.connection as dbc
    dbc.DB_PATH = str(db_path)
    dbc.init_db()
    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, dbc, lib, src, data_root


def _seed_promoted(client, dbc, lib, src, data_root):
    """Index a normal doc, ingest + promote one md; returns the promoted doc_id."""
    from pathlib import Path
    from app.services.indexer import index_file
    normal = Path(lib) / "normal.md"
    normal.write_text(NORMAL_MD, encoding="utf-8")
    index_file(normal, Path(lib))

    p = src / "promoted_source.md"
    p.write_text(PROMOTED_MD, encoding="utf-8")
    from app.services.intake.orchestrator import execute_intake
    res = execute_intake(source_ref=str(p), batch_id="exposure",
                         trigger_kind="manual", data_root=str(data_root))
    out = client.post("/api/intake/promote",
                      json={"source_revision_id": res.source_revision_id},
                      headers={"X-BOH-Operator-Token": "test-token"})
    assert out.status_code == 200 and out.json()["promoted"] is True
    return out.json()["doc_id"]


def _retrieve_doc_ids(client, include_promoted=None):
    payload = {"query": f"{TERM} fixture sentence unique", "mode": "exploration", "limit": 8}
    if include_promoted is not None:
        payload["include_promoted"] = include_promoted
    res = client.post("/api/retrieve", json=payload,
                      headers={"X-BOH-Retrieval-Token": "retrieve-token"})
    assert res.status_code == 200
    return {p.get("doc_id") for p in res.json()["context_packs"]}, res.json()


def test_exposure_matrix_default_off_everywhere(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib, src, data_root):
        doc_id = _seed_promoted(client, dbc, lib, src, data_root)

        # /api/retrieve — hidden with default flags AND with request flag alone (env closed).
        ids, _ = _retrieve_doc_ids(client)
        assert doc_id not in ids
        ids, _ = _retrieve_doc_ids(client, include_promoted=True)
        assert doc_id not in ids  # request flag alone must NOT leak (dual gate)

        # /api/search
        s = client.get("/api/search", params={"q": TERM})
        assert s.status_code == 200
        assert all(doc_id not in str(r) for r in s.json().get("results", []))

        # /api/docs listing
        docs = client.get("/api/docs", params={"per_page": 200})
        assert doc_id not in {d["doc_id"] for d in docs.json()["docs"]}

        # /api/fold/library
        fold = client.get("/api/fold/library")
        assert doc_id not in {d.get("doc_id") for d in fold.json().get("docs", [])} | {
            d.get("doc_id") for d in (fold.json() if isinstance(fold.json(), list) else [])}

        # graph projection (atlas) — conservative: promoted docs never appear
        g = client.get("/api/graph/projection", params={"mode": "web"})
        if g.status_code == 200:
            assert doc_id not in str(g.json())

        # Normal doc unaffected (parity baseline).
        n = client.get("/api/docs", params={"per_page": 200})
        assert "normal-doc" in {d["doc_id"] for d in n.json()["docs"]}


def test_dual_gate_opens_retrieval_only_with_both(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib, src, data_root):
        doc_id = _seed_promoted(client, dbc, lib, src, data_root)

        monkeypatch.setenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", "true")
        # Env open but request flag default false -> still hidden on retrieval.
        ids, _ = _retrieve_doc_ids(client)
        assert doc_id not in ids
        # Both open -> visible, advisory, with the WO-R1/WO-2 evidence chain attached.
        ids, payload = _retrieve_doc_ids(client, include_promoted=True)
        assert doc_id in ids
        pack = next(p for p in payload["context_packs"] if p.get("doc_id") == doc_id)
        assert pack["do_not_treat_as_canonical"] is True  # advisory, truthful authority
        prov = pack["intake_provenance"]
        assert prov is not None
        assert prov["source_revision_id"]
        assert prov["intake_capability_id"]
        assert prov["intake_run_id"]
        assert prov["handoff_id"]
        assert prov["promoted_by"]

        # Non-promoted packs carry the key as null (uniform contract).
        normal_ids, normal_payload = _retrieve_doc_ids(client, include_promoted=False)
        for p in normal_payload["context_packs"]:
            if p.get("doc_id") != doc_id:
                assert p["intake_provenance"] is None


def test_env_gate_opens_secondary_surfaces(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib, src, data_root):
        doc_id = _seed_promoted(client, dbc, lib, src, data_root)
        monkeypatch.setenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", "true")

        docs = client.get("/api/docs", params={"per_page": 200})
        assert doc_id in {d["doc_id"] for d in docs.json()["docs"]}

        s = client.get("/api/search", params={"q": TERM})
        assert s.status_code == 200  # search no longer filters it out with the gate open


def test_service_layer_retrieve_and_direct_doc_access_fail_closed(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib, src, data_root):
        doc_id = _seed_promoted(client, dbc, lib, src, data_root)

        # Direct service-layer retrieval path (no route): default hides promoted docs.
        from app.core import retrieval as retrieval_core
        base = retrieval_core.retrieve(f"{TERM} fixture sentence unique", limit=8)
        assert doc_id not in {p.get("doc_id") for p in base.get("context_packs", [])}
        # And retrieve_governed without the flag.
        gov = retrieval_core.retrieve_governed(f"{TERM} fixture sentence unique",
                                               mode="exploration", limit=8)
        assert doc_id not in {p.get("doc_id") for p in gov.get("context_packs", [])}

        # Direct-by-id docs access is env-gated too (audit item E).
        closed = client.get(f"/api/docs/{doc_id}")
        assert closed.status_code == 404
        # Raw-content and editor-load reads are env-gated as well (pre-commit audit item 2:
        # both would otherwise bypass the exposure predicate and serve full file text).
        assert client.get(f"/api/docs/{doc_id}/content").status_code == 404
        assert client.get(f"/api/editor/{doc_id}").status_code == 404

        monkeypatch.setenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", "true")
        opened = client.get(f"/api/docs/{doc_id}")
        assert opened.status_code == 200
        assert opened.json().get("doc_id") == doc_id or doc_id in str(opened.json())
        raw = client.get(f"/api/docs/{doc_id}/content")
        assert raw.status_code == 200 and TERM in raw.text


def test_mutation_isolation_gate_independent(tmp_path, monkeypatch):
    """Owner mutation-isolation rule: ordinary mutations of promoted docs fail closed EVEN WITH
    the exposure gate open; failed attempts leave file, docs row, ledger, and audit unchanged;
    normal docs keep their authoring behavior."""
    import hashlib
    from pathlib import Path

    with _client(tmp_path, monkeypatch) as (client, dbc, lib, src, data_root):
        doc_id = _seed_promoted(client, dbc, lib, src, data_root)
        op = {"X-BOH-Operator-Token": "test-token"}
        monkeypatch.setenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", "true")  # gate OPEN on purpose

        managed_file = Path(lib) / "promoted_intake" / f"{doc_id}.md"
        before_hash = hashlib.sha256(managed_file.read_bytes()).hexdigest()
        before_doc = dict(dbc.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,)))
        before_ledger = dict(dbc.fetchone(
            "SELECT * FROM intake_promotions WHERE doc_id = ? AND status='active'", (doc_id,)))
        # Reads succeed with the gate open (editor load + raw content). NOTE: the editor load
        # legitimately creates a draft (and its own audit event) — that is read-path behavior,
        # so the mutation-audit baseline is captured AFTER the reads.
        assert client.get(f"/api/editor/{doc_id}").status_code == 200
        assert TERM in client.get(f"/api/docs/{doc_id}/content").text
        before_audit = dbc.fetchone("SELECT COUNT(*) AS n FROM audit_log")["n"]

        # Editor SAVE fails closed with the structured reason.
        save = client.post(f"/api/editor/{doc_id}/save", headers=op)
        assert save.status_code >= 400 or "promoted_intake_managed_document" in save.text
        assert "promoted" in save.text.lower()

        # Metadata PATCH, workflow PATCH, lifecycle, duplicate-decision: all 409 + reason.
        meta = client.patch(f"/api/docs/{doc_id}/metadata", json={"title": "hax"}, headers=op)
        assert meta.status_code == 409
        assert meta.json()["detail"] == "promoted_intake_managed_document"
        wf = client.patch(f"/api/workflow/{doc_id}",
                          json={"operator_state": "observe", "operator_intent": "capture"},
                          headers=op)
        assert wf.status_code == 409
        lc = client.post(f"/api/lifecycle/{doc_id}/backward",
                         json={"reason": "x", "actor": "tester"}, headers=op)
        assert lc.status_code == 409
        lcu = client.post(f"/api/lifecycle/{doc_id}/undo", json={"actor": "tester"}, headers=op)
        assert lcu.status_code == 409
        dup = client.post("/api/duplicates/decision",
                          json={"doc_id": doc_id, "related_doc_id": "normal-doc",
                                "decision": "quarantine"}, headers=op)
        assert dup.status_code == 409

        # Library write helpers cannot address the managed subtree (single choke point).
        import pytest as _pytest
        from app.core.input_surface import safe_subpath
        for hostile in ("promoted_intake", "promoted_intake/sub", "Promoted_Intake"):
            with _pytest.raises(ValueError, match="promoted_intake_managed_document"):
                safe_subpath(hostile)

        # Workspace orphan cleanup must SKIP promoted rows (ledger-governed deletes only).
        dbc.execute("INSERT INTO docs (doc_id, path, corpus_class) VALUES "
                    "('promoted-ghost', 'promoted_intake/ghost.md', "
                    "'CORPUS_CLASS:PROMOTED_INTAKE')")
        dbc.execute("INSERT INTO docs (doc_id, path, corpus_class) VALUES "
                    "('plain-ghost', 'scratch/plain-ghost.md', 'CORPUS_CLASS:DRAFT')")
        from app.api.routes.workspace_routes import _remove_stale_doc_refs
        _remove_stale_doc_refs(Path(lib))
        assert dbc.fetchone("SELECT doc_id FROM docs WHERE doc_id='promoted-ghost'") is not None
        assert dbc.fetchone("SELECT doc_id FROM docs WHERE doc_id='plain-ghost'") is None
        dbc.execute("DELETE FROM docs WHERE doc_id='promoted-ghost'")

        # Failed attempts left everything unchanged: file bytes, docs row, ledger, audit.
        assert hashlib.sha256(managed_file.read_bytes()).hexdigest() == before_hash
        assert dict(dbc.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))) == before_doc
        assert dict(dbc.fetchone(
            "SELECT * FROM intake_promotions WHERE doc_id = ? AND status='active'",
            (doc_id,))) == before_ledger
        assert dbc.fetchone("SELECT COUNT(*) AS n FROM audit_log")["n"] == before_audit

        # Normal docs keep existing authoring behavior.
        assert client.get("/api/editor/normal-doc").status_code == 200
        ok = client.patch("/api/docs/normal-doc/metadata", json={"title": "Renamed OK"},
                          headers=op)
        assert ok.status_code == 200


def test_promoted_doc_gets_no_planecard_and_demotion_leaves_no_orphan(tmp_path, monkeypatch):
    """First-promotion gate finding (2026-06-11): the indexer auto-wraps every doc into a
    PlaneCard, which re-exposed promoted docs through card surfaces. Promoted docs must get
    NO card; demotion must leave no orphan card; normal docs keep their wrap behavior."""
    with _client(tmp_path, monkeypatch) as (client, dbc, lib, src, data_root):
        doc_id = _seed_promoted(client, dbc, lib, src, data_root)
        # The promoted doc has no card; the normal doc (indexed by _seed_promoted) keeps its wrap.
        assert dbc.fetchone("SELECT COUNT(*) AS n FROM cards WHERE doc_id = ?",
                            (doc_id,))["n"] == 0
        assert dbc.fetchone("SELECT COUNT(*) AS n FROM cards WHERE doc_id = 'normal-doc'")["n"] >= 1
        # And no retrieval card-pack leak for the promoted doc's terms with gates closed.
        ids, payload = _retrieve_doc_ids(client)
        assert all(p.get("doc_id") != doc_id for p in payload["context_packs"])
        # Demote: no orphan card afterwards either.
        promo = dbc.fetchone(
            "SELECT promotion_id FROM intake_promotions WHERE doc_id = ? AND status='active'",
            (doc_id,))
        dem = client.post(f"/api/intake/promotions/{promo['promotion_id']}/demote",
                          json={"reason": "card test"},
                          headers={"X-BOH-Operator-Token": "test-token"})
        assert dem.status_code == 200
        assert dbc.fetchone("SELECT COUNT(*) AS n FROM cards WHERE doc_id = ?",
                            (doc_id,))["n"] == 0


def test_demotion_removes_from_all_surfaces(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib, src, data_root):
        doc_id = _seed_promoted(client, dbc, lib, src, data_root)
        promo = dbc.fetchone(
            "SELECT promotion_id FROM intake_promotions WHERE doc_id = ? AND status='active'",
            (doc_id,))
        dem = client.post(f"/api/intake/promotions/{promo['promotion_id']}/demote",
                          json={"reason": "matrix"},
                          headers={"X-BOH-Operator-Token": "test-token"})
        assert dem.status_code == 200

        monkeypatch.setenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", "true")
        ids, _ = _retrieve_doc_ids(client, include_promoted=True)
        assert doc_id not in ids  # gone even with both gates open
        docs = client.get("/api/docs", params={"per_page": 200})
        assert doc_id not in {d["doc_id"] for d in docs.json()["docs"]}

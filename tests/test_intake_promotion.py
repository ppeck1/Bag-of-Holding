"""WO-2 promotion runtime tests (temp DBs/fixtures only; the real boh.db is never touched).

Covers: durable handoff-row persistence (slice A), the promotion service (slice B: fail-closed
eligibility, idempotency, supersede, provenance-scoped demotion, DEC-0003 era-convergence,
backfill), and the operator-gated routes (slice C).
"""

import importlib
import json
import os
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

MD = "# Promo Doc\n\nUnique promotion fixture content with enough words to be queryable.\n"
HTML = ("<html><body><p>Neutralized promotion html fixture with enough words here.</p>"
        "<script>x()</script></body></html>")


@contextmanager
def _env(tmp_path, monkeypatch, *, with_client=False):
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

    if with_client:
        import app.api.main as main
        importlib.reload(main)
        main.db.DB_PATH = str(db_path)
        main.db.init_db()
        with TestClient(main.app) as client:
            yield client, dbc, src, data_root
    else:
        yield None, dbc, src, data_root


def _ingest(src, data_root, name, content, batch="promo-test"):
    path = src / name
    path.write_text(content, encoding="utf-8")
    from app.services.intake.orchestrator import execute_intake
    return execute_intake(source_ref=str(path), batch_id=batch,
                          trigger_kind="manual", data_root=str(data_root))


def _one(dbc, sql, params=()):
    return dbc.fetchone(sql, params)


# ── Slice A: durable handoff rows ────────────────────────────────────────────────


def test_pipeline_persists_ready_handoff_row(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        res = _ingest(src, data_root, "a.md", MD)
        assert res.outcome == "processed"
        row = _one(dbc, "SELECT * FROM intake_handoffs WHERE source_revision_id = ?",
                   (res.source_revision_id,))
        assert row is not None
        assert row["handoff_ready"] == 1
        assert row["intake_run_id"] == res.run_id
        assert row["intake_capability_id"] == res.intake_capability_id
        assert row["normalized_output_type"] == "markdown"
        assert row["normalized_output_profile"] is None
        assert row["adapter_registry_version"].startswith("adapterfp-v1:")
        assert row["policy_snapshot_hash"] == "policy-unbound-v1"
        assert isinstance(json.loads(row["warnings_json"]), list)


def test_html_handoff_carries_neutralized_profile(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        res = _ingest(src, data_root, "p.html", HTML)
        row = _one(dbc, "SELECT * FROM intake_handoffs WHERE source_revision_id = ?",
                   (res.source_revision_id,))
        assert row["normalized_output_type"] == "markdown"        # artifact representation
        assert row["normalized_output_profile"] == "html_neutralized_markdown"  # DEC-0004.2


def test_held_unsupported_creates_no_handoff_row(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        res = _ingest(src, data_root, "weird.xyz", "unsupported bytes")
        row = _one(dbc, "SELECT * FROM intake_handoffs WHERE source_revision_id = ?",
                   (res.source_revision_id,))
        assert row is None


# ── Slice B: promotion service ───────────────────────────────────────────────────


def test_promote_happy_path_and_idempotency(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        res = _ingest(src, data_root, "a.md", MD)

        out = promotion.promote(source_revision_id=res.source_revision_id)
        assert out["promoted"] is True
        doc = _one(dbc, "SELECT * FROM docs WHERE doc_id = ?", (out["doc_id"],))
        assert doc is not None
        assert doc["corpus_class"] == "CORPUS_CLASS:PROMOTED_INTAKE"
        # Advisory, never canonical (DEC-0004.4 / canon-truthfulness invariant).
        assert doc["status"] != "canonical"
        assert doc["authority_state"] not in ("approved", "trusted", "canonical")
        ledger = _one(dbc, "SELECT * FROM intake_promotions WHERE promotion_id = ?",
                      (out["promotion_id"],))
        assert ledger["status"] == "active"
        assert ledger["handoff_id"]
        audit = _one(dbc, "SELECT * FROM audit_log WHERE event_type = 'intake_promotion'")
        assert audit is not None

        again = promotion.promote(source_revision_id=res.source_revision_id)
        assert again.get("idempotent") is True
        assert again["doc_id"] == out["doc_id"]
        n = _one(dbc, "SELECT COUNT(*) AS n FROM intake_promotions")["n"]
        assert n == 1


def test_promote_fails_closed_on_hold_lane_and_missing_handoff(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        res = _ingest(src, data_root, "p.html", HTML)  # html -> advisory safety_lane=hold
        out = promotion.promote(source_revision_id=res.source_revision_id)
        assert out["promoted"] is False
        assert any(r.startswith("safety_lane_not_accept") for r in out["reasons"])

        missing = promotion.promote(source_revision_id="srid-that-does-not-exist")
        assert missing["promoted"] is False
        assert missing["reasons"] == ["no_ready_handoff"]


def test_demote_is_provenance_scoped_and_reversible(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        from app.services.indexer import index_file
        from pathlib import Path
        # Unrelated normal doc that must survive demotion untouched.
        lib = Path(dbc.DB_PATH).parent / "library"
        bystander = lib / "bystander.md"
        bystander.write_text("---\nboh:\n  id: \"bystander-doc\"\n  title: \"Bystander\"\n"
                             "  status: \"draft\"\n  authority_state: \"draft\"\n---\n\n# B\n\n"
                             "Bystander content stays.\n", encoding="utf-8")
        index_file(bystander, lib)

        res = _ingest(src, data_root, "a.md", MD)
        out = promotion.promote(source_revision_id=res.source_revision_id)
        intake_counts_before = {t: _one(dbc, f"SELECT COUNT(*) AS n FROM {t}")["n"]
                                for t in ("intake_source_revisions", "intake_runs",
                                          "intake_capabilities", "intake_handoffs")}

        dem = promotion.demote(out["promotion_id"], reason="test")
        assert dem["demoted"] is True
        assert _one(dbc, "SELECT * FROM docs WHERE doc_id = ?", (out["doc_id"],)) is None
        assert _one(dbc, "SELECT COUNT(*) AS n FROM doc_chunks WHERE doc_id = ?",
                    (out["doc_id"],))["n"] == 0
        assert _one(dbc, "SELECT * FROM docs WHERE doc_id = 'bystander-doc'") is not None
        ledger = _one(dbc, "SELECT * FROM intake_promotions WHERE promotion_id = ?",
                      (out["promotion_id"],))
        assert ledger["status"] == "demoted" and ledger["demoted_by"] and ledger["demoted_at"]
        for t, n in intake_counts_before.items():
            assert _one(dbc, f"SELECT COUNT(*) AS n FROM {t}")["n"] == n  # intake untouched

        again = promotion.demote(out["promotion_id"])
        assert again.get("idempotent") is True
        # Re-promote after demotion is allowed (reversibility) — partial unique permits it.
        re_out = promotion.promote(source_revision_id=res.source_revision_id)
        assert re_out["promoted"] is True


def test_changed_revision_supersedes_prior_promotion(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        res1 = _ingest(src, data_root, "a.md", MD)
        first = promotion.promote(source_revision_id=res1.source_revision_id)
        res2 = _ingest(src, data_root, "a.md", MD + "\nChanged content line for new revision.\n")
        assert res2.source_revision_id != res1.source_revision_id
        second = promotion.promote(source_revision_id=res2.source_revision_id)
        assert second["promoted"] is True
        assert second["supersedes_promotion_id"] == first["promotion_id"]
        old = _one(dbc, "SELECT status FROM intake_promotions WHERE promotion_id = ?",
                   (first["promotion_id"],))
        assert old["status"] == "superseded"
        lin = _one(dbc, "SELECT * FROM lineage WHERE doc_id = ? AND related_doc_id = ? "
                        "AND relationship = 'supersedes'",
                   (second["doc_id"], first["doc_id"]))
        assert lin is not None


def test_dec0003_fingerprint_era_capability_promotes_through_older_artifact(tmp_path, monkeypatch):
    """DEC-0003 runtime acceptance case: a second fingerprint era re-mints revision/run/capability
    while the content-identical artifact row converges on era 1; promotion preserves the full
    new-era chain while resolving to the older artifact identity."""
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        res1 = _ingest(src, data_root, "a.md", MD, batch="era1")
        h1 = _one(dbc, "SELECT * FROM intake_handoffs WHERE source_revision_id = ?",
                  (res1.source_revision_id,))

        from app.services.intake import orchestrator
        monkeypatch.setattr(orchestrator, "adapter_registry_fingerprint",
                            lambda: "adapterfp-v1:era2test")
        res2 = _ingest(src, data_root, "a.md", MD, batch="era2")
        assert res2.outcome == "processed"
        assert res2.source_revision_id != res1.source_revision_id
        h2 = _one(dbc, "SELECT * FROM intake_handoffs WHERE source_revision_id = ?",
                  (res2.source_revision_id,))
        # Artifact identity converged on the era-1 row; era-2 chain is its own.
        assert h2["normalized_artifact_id"] == h1["normalized_artifact_id"]
        assert h2["intake_run_id"] != h1["intake_run_id"]
        assert h2["intake_capability_id"] != h1["intake_capability_id"]
        assert h2["adapter_registry_version"] == "adapterfp-v1:era2test"

        out = promotion.promote(source_revision_id=res2.source_revision_id)
        assert out["promoted"] is True
        ledger = _one(dbc, "SELECT * FROM intake_promotions WHERE promotion_id = ?",
                      (out["promotion_id"],))
        assert ledger["normalized_artifact_id"] == h1["normalized_artifact_id"]  # older artifact
        assert ledger["intake_capability_id"] == h2["intake_capability_id"]      # new capability
        assert ledger["adapter_registry_version"] == "adapterfp-v1:era2test"     # new contract


def test_backfill_reconstructs_handoffs_from_durable_rows(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        res = _ingest(src, data_root, "a.md", MD)
        # Simulate the pre-handoff era by removing the durable row the pipeline just wrote.
        conn = sqlite3.connect(dbc.DB_PATH)
        conn.execute("DELETE FROM intake_handoffs")
        conn.commit()
        conn.close()

        plan = promotion.backfill_handoffs(dry_run=True)
        assert plan["dry_run"] is True and plan["planned"] == 1
        assert _one(dbc, "SELECT COUNT(*) AS n FROM intake_handoffs")["n"] == 0  # dry run wrote 0

        done = promotion.backfill_handoffs(dry_run=False)
        assert done["planned"] == 1
        row = _one(dbc, "SELECT * FROM intake_handoffs WHERE source_revision_id = ?",
                   (res.source_revision_id,))
        assert row is not None and row["handoff_ready"] == 1
        assert json.loads(row["warnings_json"]) == ["backfilled_handoff"]
        # And the backfilled handoff is promotable.
        out = promotion.promote(source_revision_id=res.source_revision_id)
        assert out["promoted"] is True


# ── Slice C: operator-gated routes ───────────────────────────────────────────────


def test_promotion_routes_operator_gated_and_functional(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch, with_client=True) as (client, dbc, src, data_root):
        res = _ingest(src, data_root, "a.md", MD)

        # Audit item B: the promotable listing is operator-gated (exposes provenance metadata).
        denied_listing = client.get("/api/intake/promotable")
        assert denied_listing.status_code == 401
        listing = client.get("/api/intake/promotable",
                             headers={"X-BOH-Operator-Token": "test-token"})
        assert listing.status_code == 200
        entries = listing.json()["promotable"]
        assert any(e["source_revision_id"] == res.source_revision_id and e["eligible"]
                   for e in entries)

        denied = client.post("/api/intake/promote",
                             json={"source_revision_id": res.source_revision_id})
        assert denied.status_code == 401

        ok = client.post("/api/intake/promote",
                         json={"source_revision_id": res.source_revision_id},
                         headers={"X-BOH-Operator-Token": "test-token"})
        assert ok.status_code == 200
        body = ok.json()
        assert body["promoted"] is True

        bad = client.post("/api/intake/promote", json={},
                          headers={"X-BOH-Operator-Token": "test-token"})
        assert bad.status_code == 422

        dem_denied = client.post(f"/api/intake/promotions/{body['promotion_id']}/demote")
        assert dem_denied.status_code == 401
        dem = client.post(f"/api/intake/promotions/{body['promotion_id']}/demote",
                          json={"reason": "route test"},
                          headers={"X-BOH-Operator-Token": "test-token"})
        assert dem.status_code == 200
        assert dem.json()["demoted"] is True

        missing = client.post("/api/intake/promotions/promo_nope/demote",
                              json={}, headers={"X-BOH-Operator-Token": "test-token"})
        assert missing.status_code == 404


# ── Audit item A: cross-domain failure injection ─────────────────────────────────


def test_index_failure_fails_closed_and_retry_reconciles(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        import app.services.indexer as idx
        res = _ingest(src, data_root, "a.md", MD)

        def boom(path, root):
            raise RuntimeError("injected index failure")

        orig = idx.index_file
        idx.index_file = boom
        try:
            out = promotion.promote(source_revision_id=res.source_revision_id)
        finally:
            idx.index_file = orig
        assert out["promoted"] is False
        assert out["reasons"] == ["promotion_io_failed:RuntimeError"]
        # No exposed doc, no active ledger winner.
        assert _one(dbc, "SELECT * FROM docs WHERE doc_id LIKE 'promoted-%'") is None
        assert _one(dbc, "SELECT * FROM intake_promotions") is None
        # The orphan managed file, if independently indexed by a scan, is STILL marker-excluded.
        from pathlib import Path
        lib = Path(dbc.DB_PATH).parent / "library"
        orphan = next((lib / "promoted_intake").glob("*.md"))
        idx.index_file(orphan, lib)
        row = _one(dbc, "SELECT corpus_class FROM docs WHERE doc_id LIKE 'promoted-%'")
        assert row["corpus_class"] == "CORPUS_CLASS:PROMOTED_INTAKE"
        # Deterministic retry reconciles every partial state.
        out2 = promotion.promote(source_revision_id=res.source_revision_id)
        assert out2["promoted"] is True


def test_ledger_failure_rolls_back_without_exposure(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        res = _ingest(src, data_root, "a.md", MD)

        def boom(conn, event_type, detail):
            raise RuntimeError("injected audit failure")

        orig = promotion._audit
        promotion._audit = boom
        try:
            out = promotion.promote(source_revision_id=res.source_revision_id)
        finally:
            promotion._audit = orig
        assert out["promoted"] is False
        assert out["reasons"] == ["promotion_ledger_failed:RuntimeError"]
        # Whole ledger txn rolled back: no active winner; the indexed doc exists but is
        # marker-excluded from first instant (classify rule), so nothing is exposed.
        assert _one(dbc, "SELECT * FROM intake_promotions") is None
        doc = _one(dbc, "SELECT corpus_class FROM docs WHERE doc_id LIKE 'promoted-%'")
        assert doc is not None and doc["corpus_class"] == "CORPUS_CLASS:PROMOTED_INTAKE"
        # Retry is idempotent and heals.
        out2 = promotion.promote(source_revision_id=res.source_revision_id)
        assert out2["promoted"] is True
        out3 = promotion.promote(source_revision_id=res.source_revision_id)
        assert out3.get("idempotent") is True and out3["doc_id"] == out2["doc_id"]


# ── Audit item C: path containment ───────────────────────────────────────────────


def test_artifact_path_containment_fails_closed(tmp_path, monkeypatch):
    import sqlite3 as _sq
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        res = _ingest(src, data_root, "a.md", MD)
        # Backslash separators and drive prefixes only mean traversal on Windows;
        # on POSIX they are literal filename bytes (still fail closed, but with
        # normalized_file_missing rather than containment). Test each platform's
        # genuine escape forms.
        hostile = [
            "../../evil.md",                         # parent traversal (both platforms)
        ]
        if os.name == "nt":
            hostile += [
                "..\\..\\evil.md",                   # parent traversal, native separators
                "../..\\evil.md",                    # mixed separators
                "C:\\Windows\\system32\\drivers\\etc\\hosts",  # absolute outside root
                "Z:\\other_drive\\evil.md",          # unexpected drive prefix
            ]
        else:
            hostile += ["/etc/hosts"]                # absolute outside root
        for bad in hostile:
            conn = _sq.connect(dbc.DB_PATH)
            conn.execute("UPDATE intake_normalized_artifacts SET output_path = ?", (bad,))
            conn.commit()
            conn.close()
            out = promotion.promote(source_revision_id=res.source_revision_id)
            assert out["promoted"] is False, bad
            assert "artifact_path_outside_data_root" in out["reasons"], (bad, out)

        # Unset data root -> fail closed too.
        monkeypatch.delenv("BOH_DATA_ROOT")
        out = promotion.promote(source_revision_id=res.source_revision_id)
        assert out["promoted"] is False
        assert "data_root_not_configured" in out["reasons"]


def test_destination_containment_rejects_escapes(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, _dbc, _src, _data_root):
        from app.services.intake import promotion
        import pytest as _pytest
        hostile = ["../evil", "sub/../../evil"]
        if os.name == "nt":
            # Backslashes are separators only on Windows; on POSIX they are
            # literal filename bytes and resolve inside the managed dir.
            hostile += ["..\\evil", "sub\\..\\..\\evil"]
        for h in hostile:
            with _pytest.raises(ValueError):
                promotion._promoted_dest(h)
        # ".." alone is NOT an escape: it forms the literal filename "...md" inside the
        # managed dir (containment-checked on the resolved path), so it is accepted.
        inside = promotion._promoted_dest("..")
        assert "promoted_intake" in str(inside.resolve())
        ok = promotion._promoted_dest("deadbeefdeadbeef")
        assert ok.name == "deadbeefdeadbeef.md"
        assert "promoted_intake" in str(ok)


# ── Audit item D: handoff-event semantics ────────────────────────────────────────


def test_replay_appends_second_handoff_event_latest_wins(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        from app.services.intake.orchestrator import replay_revision
        res = _ingest(src, data_root, "a.md", MD)
        replay = replay_revision(source_revision_id=res.source_revision_id,
                                 source_ref=str(src / "a.md"), batch_id="replay-1",
                                 data_root=str(data_root))
        assert replay.outcome == "processed"
        # One row per handoff EVENT with a unique id. Replay runs under a new batch, which
        # mints a new capability id — so the two events live under the SAME revision but
        # (correctly) different capabilities.
        rows = dbc.fetchall(
            "SELECT handoff_id, intake_capability_id FROM intake_handoffs "
            "WHERE source_revision_id = ?",
            (res.source_revision_id,))
        assert len(rows) == 2
        assert len({r["handoff_id"] for r in rows}) == 2
        # list_promotable is latest-per-capability; every entry for this revision resolves to
        # the same promotion target.
        entries = [e for e in promotion.list_promotable()
                   if e["source_revision_id"] == res.source_revision_id]
        assert len(entries) >= 1
        per_cap = {}
        for e in entries:
            per_cap.setdefault(e["intake_capability_id"], []).append(e)
        assert all(len(v) == 1 for v in per_cap.values())  # exactly one (latest) per capability
        out = promotion.promote(source_revision_id=res.source_revision_id)
        assert out["promoted"] is True
        again = promotion.promote(source_revision_id=res.source_revision_id)
        assert again.get("idempotent") is True


def test_demote_of_superseded_promotion_allowed(tmp_path, monkeypatch):
    with _env(tmp_path, monkeypatch) as (_c, dbc, src, data_root):
        from app.services.intake import promotion
        res1 = _ingest(src, data_root, "a.md", MD)
        first = promotion.promote(source_revision_id=res1.source_revision_id)
        res2 = _ingest(src, data_root, "a.md", MD + "\nNew revision content line.\n")
        second = promotion.promote(source_revision_id=res2.source_revision_id)

        dem = promotion.demote(first["promotion_id"], reason="superseded cleanup")
        assert dem["demoted"] is True
        assert _one(dbc, "SELECT * FROM docs WHERE doc_id = ?", (first["doc_id"],)) is None
        # The superseding active promotion and its doc are untouched.
        assert _one(dbc, "SELECT * FROM docs WHERE doc_id = ?", (second["doc_id"],)) is not None
        assert _one(dbc, "SELECT status FROM intake_promotions WHERE promotion_id = ?",
                    (second["promotion_id"],))["status"] == "active"

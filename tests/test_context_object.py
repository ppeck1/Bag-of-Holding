"""WO-R2 /api/context-object tests (temp DBs only; retrieval-token posture, composition,
determinism, empty-scope honesty, blocking grounding, promoted exclusion)."""

import importlib
import json
from contextlib import contextmanager

from fastapi.testclient import TestClient

DOC = """---
boh:
  id: "ctx-doc"
  title: "Context Object Target"
  status: "draft"
  authority_state: "draft"
  project: "CtxProj"
---

# Context Object Target

Assembler fixture content with enough unique words for retrieval xylophone.
"""


@contextmanager
def _client(tmp_path, monkeypatch):
    lib = tmp_path / "library"
    lib.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_LIBRARY", str(lib))
    monkeypatch.setenv("BOH_RETRIEVAL_TOKEN", "retrieve-token")
    monkeypatch.delenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", raising=False)
    import app.db.connection as dbc
    dbc.DB_PATH = str(db_path)
    dbc.init_db()
    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, dbc, lib


def _seed(dbc, lib):
    from pathlib import Path
    from app.services.indexer import index_file
    p = Path(lib) / "ctx.md"
    p.write_text(DOC, encoding="utf-8")
    index_file(p, Path(lib))


def _auth():
    return {"X-BOH-Retrieval-Token": "retrieve-token"}


def test_token_required_fail_closed(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        assert client.get("/api/context-object", params={"scope": "doc:x"}).status_code == 401
        assert client.post("/api/context-object",
                           json={"scope": {"type": "query", "query": "x"}}).status_code == 401
        bad = client.get("/api/context-object", params={"scope": "doc:x"},
                         headers={"X-BOH-Retrieval-Token": "wrong"})
        assert bad.status_code == 403


def test_doc_scope_composition_and_determinism(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        r1 = client.get("/api/context-object", params={"scope": "doc:ctx-doc"},
                        headers=_auth())
        assert r1.status_code == 200
        body = r1.json()
        assert set(body) >= {"scope", "state", "evidence", "conflicts", "unknowns", "actions"}
        assert body["scope"]["requested"] == {"type": "doc", "value": "ctx-doc"}
        assert body["scope"]["resolved"]["member_count"] == 1
        assert body["scope"]["ambiguous"] is False
        assert body["state"]["kind"] == "node"
        assert "currentness_label" in body["state"]
        assert any(p.get("doc_id") == "ctx-doc" for p in body["evidence"])
        # Determinism: identical second call.
        r2 = client.get("/api/context-object", params={"scope": "doc:ctx-doc"},
                        headers=_auth())
        assert json.dumps(r1.json(), sort_keys=True) == json.dumps(r2.json(), sort_keys=True)


def test_project_scope_and_query_post(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        proj = client.get("/api/context-object", params={"scope": "project:CtxProj"},
                          headers=_auth())
        assert proj.status_code == 200
        assert proj.json()["scope"]["resolved"]["member_count"] == 1
        assert proj.json()["state"]["kind"] == "membership"

        q = client.post("/api/context-object",
                        json={"scope": {"type": "query", "query": "xylophone assembler"}},
                        headers=_auth())
        assert q.status_code == 200
        assert "ctx-doc" in {p.get("doc_id") for p in q.json()["evidence"]}
        assert q.json()["scope"]["resolved"]["member_count"] >= 1


def test_empty_scope_and_validation(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        empty = client.get("/api/context-object", params={"scope": "project:NoSuchProject"},
                           headers=_auth())
        assert empty.status_code == 200
        assert empty.json()["scope"]["resolved"] is None
        assert "empty_scope" in empty.json()["scope"]["warnings"]
        assert empty.json()["evidence"] == []
        assert client.get("/api/context-object", params={"scope": "badformat"},
                          headers=_auth()).status_code == 422
        assert client.get("/api/context-object", params={"scope": "query:not-on-get"},
                          headers=_auth()).status_code == 422


def test_only_blocking_returns_grounded_blockers(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        dbc.execute(
            "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, "
            "acknowledged) VALUES (?,?,?,?,?,?)",
            ("definition_conflict", "ctx-doc,other", "xylophone", "p", 1, 0))
        r = client.get("/api/context-object",
                       params={"scope": "doc:ctx-doc", "only": "blocking"}, headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["evidence"] == []  # reduced payload
        assert body["blockers"], body
        b = body["blockers"][0]
        assert b["blocker"] == "open_conflict"
        assert b["source"].startswith("conflict:")
        assert b["evidence_refs"] and b["provenance"] in ("direct", "computed")
        # The open conflict also grounds an executable advisory action.
        full = client.get("/api/context-object", params={"scope": "doc:ctx-doc"},
                          headers=_auth()).json()
        act = next(a for a in full["actions"] if a["action_type"] == "acknowledge_conflict")
        assert act["executability"] == "executable_now"
        assert act["requires_operator_approval"] is True


def test_promoted_docs_excluded_by_default(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        dbc.execute("INSERT INTO docs (doc_id, path, project, corpus_class) VALUES "
                    "('promoted-ghost', 'promoted_intake/g.md', 'CtxProj', "
                    "'CORPUS_CLASS:PROMOTED_INTAKE')")
        r = client.get("/api/context-object", params={"scope": "project:CtxProj"},
                       headers=_auth())
        assert r.json()["scope"]["resolved"]["member_count"] == 1  # ghost excluded
        d = client.get("/api/context-object", params={"scope": "doc:promoted-ghost"},
                       headers=_auth())
        assert d.json()["scope"]["resolved"] is None
        assert "scope_not_found" in d.json()["scope"]["warnings"]


# ── Pre-commit acceptance audit additions (owner items B/C/D) ────────────────────


GHOST = ("INSERT INTO docs (doc_id, path, project, corpus_class, authority_state) VALUES "
         "('promoted-ghost', 'promoted_intake/g.md', 'CtxProj', "
         "'CORPUS_CLASS:PROMOTED_INTAKE', 'draft')")


def _no_ghost_anywhere(body):
    # `scope.requested` is the contract-mandated caller echo — it legitimately repeats the
    # requester's own input and is not a leak. Everything else must be ghost-free.
    redacted = dict(body)
    scope = dict(redacted.get("scope") or {})
    scope.pop("requested", None)
    redacted["scope"] = scope
    assert "promoted-ghost" not in json.dumps(redacted)


def test_dual_gate_matrix_across_all_scopes(tmp_path, monkeypatch):
    """Full 4-combo gate matrix; with the gate closed, the promoted doc must not leak through
    membership, resolved counts, evidence, refs, state, conflicts, unknowns, actions, warnings,
    or truncation metadata — on every scope form, including only=blocking."""
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        dbc.execute(GHOST)
        dbc.execute("INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, "
                    "detected_ts, acknowledged) VALUES "
                    "('definition_conflict', 'promoted-ghost,other', 'ghostterm', 'p', 1, 0)")

        def calls(opt_in):
            out = []
            for scope in ("doc:promoted-ghost", "project:CtxProj", "plane:informational"):
                out.append(client.get("/api/context-object",
                                      params={"scope": scope, "include_promoted": opt_in},
                                      headers=_auth()).json())
                out.append(client.get("/api/context-object",
                                      params={"scope": scope, "only": "blocking",
                                              "include_promoted": opt_in},
                                      headers=_auth()).json())
            out.append(client.post("/api/context-object",
                                   json={"scope": {"type": "query", "query": "ghostterm"},
                                         "include_promoted": opt_in},
                                   headers=_auth()).json())
            return out

        # env OFF + opt-in absent, and env OFF + opt-in present: both fully hidden.
        for opt_in in (False, True):
            for body in calls(opt_in):
                _no_ghost_anywhere(body)

        # env ON + opt-in absent: still hidden (dual gate).
        monkeypatch.setenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", "true")
        for body in calls(False):
            _no_ghost_anywhere(body)

        # env ON + opt-in present: doc/project scopes resolve the promoted doc.
        opened = client.get("/api/context-object",
                            params={"scope": "doc:promoted-ghost", "include_promoted": True},
                            headers=_auth()).json()
        assert opened["scope"]["resolved"] is not None
        assert opened["scope"]["resolved"]["member_count"] == 1
        proj = client.get("/api/context-object",
                          params={"scope": "project:CtxProj", "include_promoted": True},
                          headers=_auth()).json()
        assert proj["scope"]["resolved"]["member_count"] == 2
        # Plane scope is STRUCTURALLY promoted-free even with both gates open: promoted docs
        # are never card-wrapped (WO-2 gate finding), so PlaneCard membership cannot include
        # them. Documented stricter posture.
        plane = client.get("/api/context-object",
                           params={"scope": "plane:informational", "include_promoted": True},
                           headers=_auth()).json()
        _no_ghost_anywhere(plane)


def test_byte_determinism_per_scope_form(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        dbc.execute("INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, "
                    "detected_ts, acknowledged) VALUES "
                    "('definition_conflict', 'ctx-doc,o', 'xylophone', 'p', 1, 0)")
        gets = [{"scope": "doc:ctx-doc"}, {"scope": "project:CtxProj"},
                {"scope": "plane:informational"}, {"scope": "project:NoSuchProject"},
                {"scope": "doc:ctx-doc", "only": "blocking"}]
        for params in gets:
            a = client.get("/api/context-object", params=params, headers=_auth()).json()
            b = client.get("/api/context-object", params=params, headers=_auth()).json()
            assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), params
        body = {"scope": {"type": "query", "query": "xylophone assembler"}}
        a = client.post("/api/context-object", json=body, headers=_auth()).json()
        b = client.post("/api/context-object", json=body, headers=_auth()).json()
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_caps_and_truncation_warnings(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        for i in range(60):  # > SECTION_CAP open conflicts on the member
            dbc.execute("INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, "
                        "detected_ts, acknowledged) VALUES "
                        f"('definition_conflict', 'ctx-doc,x{i}', 't{i}', 'p', {i}, 0)")
        r = client.get("/api/context-object", params={"scope": "doc:ctx-doc"},
                       headers=_auth()).json()
        assert len(r["conflicts"]) == 50
        assert "conflicts_truncated" in r["scope"]["warnings"]
        assert len(r["actions"]) <= 50
        # Deterministic truncation: identical second call.
        r2 = client.get("/api/context-object", params={"scope": "doc:ctx-doc"},
                        headers=_auth()).json()
        assert json.dumps(r, sort_keys=True) == json.dumps(r2, sort_keys=True)

        # Bounded inputs: evidence cap, scope-string length, query-body length.
        assert client.get("/api/context-object",
                          params={"scope": "doc:ctx-doc", "evidence_limit": 26},
                          headers=_auth()).status_code == 422
        assert client.get("/api/context-object", params={"scope": "doc:" + "x" * 600},
                          headers=_auth()).status_code == 422
        assert client.post("/api/context-object",
                           json={"scope": {"type": "query", "query": "q" * 2001}},
                           headers=_auth()).status_code == 422


PROMOTED_MD = """---
boh:
  id: "promoted-zz"
  title: "Promoted Query Target"
  type: "promoted_intake"
  document_class: "promoted_intake"
  status: "draft"
  authority_state: "draft"
  project: "CtxProj"
---

# Promoted Query Target

The zugzwang fixture sentence is unique to this promoted document.
"""


def test_query_post_dual_gate_contract(tmp_path, monkeypatch):
    """Documented contract: query-scope POST follows the STANDARD WO-2 dual gate (env AND
    request flag) — not stricter. Visible results surface via evidence + resolved member
    count; closed-gate combinations leak nothing, including with only=blocking."""
    from pathlib import Path
    from app.services.indexer import index_file
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        pdir = Path(lib) / "promoted_intake"
        pdir.mkdir()
        f = pdir / "promoted-zz.md"
        f.write_text(PROMOTED_MD, encoding="utf-8")
        index_file(f, Path(lib))
        row = dbc.fetchone("SELECT corpus_class FROM docs WHERE doc_id='promoted-zz'")
        assert row["corpus_class"] == "CORPUS_CLASS:PROMOTED_INTAKE"  # classify rule-0

        def post(opt_in, only=None):
            body = {"scope": {"type": "query", "query": "zugzwang fixture sentence"},
                    "include_promoted": opt_in}
            if only:
                body["only"] = only
            r = client.post("/api/context-object", json=body, headers=_auth())
            assert r.status_code == 200
            return r.json()

        # env OFF + opt-in absent / present -> hidden (incl. blocking view).
        for opt_in in (False, True):
            assert "promoted-zz" not in json.dumps(post(opt_in))
            assert "promoted-zz" not in json.dumps(post(opt_in, only="blocking"))
        # env ON + opt-in absent -> still hidden.
        monkeypatch.setenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", "true")
        assert "promoted-zz" not in json.dumps(post(False))
        assert "promoted-zz" not in json.dumps(post(False, only="blocking"))
        # env ON + opt-in present -> VISIBLE through the intended fields only.
        body = post(True)
        evidence_ids = {p.get("doc_id") for p in body["evidence"]}
        assert "promoted-zz" in evidence_ids
        assert body["scope"]["resolved"]["member_count"] >= 1
        pack = next(p for p in body["evidence"] if p.get("doc_id") == "promoted-zz")
        assert pack["do_not_treat_as_canonical"] is True
        # No leak through unrelated sections: conflicts/actions/warnings stay ghost-free
        # (unknowns may legitimately describe a VISIBLE member's gaps).
        for section in ("conflicts", "actions"):
            assert "promoted-zz" not in json.dumps(body[section])
        assert "promoted-zz" not in json.dumps(body["scope"]["warnings"])


# ── WO-R3: question-type dispatch (Level 4) ──────────────────────────────────────


def _qt(client, qtype, scope="doc:ctx-doc"):
    r = client.get("/api/context-object",
                   params={"scope": scope, "question_type": qtype}, headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()


def test_question_type_composition_matrix(tmp_path, monkeypatch):
    """Each type assembles ITS sources and not the others' (per-type composition matrix);
    omitting question_type omits the section entirely (existing contract untouched)."""
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        dbc.execute("INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, "
                    "detected_ts, acknowledged) VALUES "
                    "('definition_conflict', 'ctx-doc,o', 'xylophone', 'p', 5, 0)")
        dbc.execute("INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts) "
                    "VALUES ('ctx-doc', 'older-doc', 'supersedes', 10)")
        dbc.execute("INSERT INTO open_items (id, plane_boundary, created_at, "
                    "resolution_authority, status, node_id, description) VALUES "
                    "('oi-1', 'p', '2026-06-11T00:00:00Z', 'operator', 'open', 'ctx-doc', "
                    "'open ambiguity')")
        dbc.execute("INSERT INTO provenance_artifacts (artifact_id, approval_id, action_type, "
                    "document_id, from_state, to_state, approved_by, approved_at, reason, "
                    "signature, artifact_json) VALUES ('art-q', 'ap-q', 'review_artifact', "
                    "'ctx-doc', 'draft', 'approved', 'op', 100, 'r', 's', '{}')")

        required = {
            "historical": {"timeline", "supersession_chain"},
            "operational": {"open_items", "active_promotions", "blocking_conditions"},
            "authority": {"review_history", "certificates", "open_conflicts"},
            "exploratory": {"contradiction_pairs", "neighbors"},
        }
        all_keys = set().union(*required.values())
        for qtype, keys in required.items():
            qc = _qt(client, qtype)["question_context"]
            assert qc["type"] == qtype
            assert keys <= set(qc), (qtype, qc.keys())
            assert not (all_keys - keys) & set(qc), (qtype, qc.keys())  # no other type's keys
        # Content spot-checks.
        hist = _qt(client, "historical")["question_context"]
        assert any(e["kind"] == "lineage" and e["what"] == "supersedes"
                   for e in hist["timeline"])
        assert hist["supersession_chain"]
        op = _qt(client, "operational")["question_context"]
        assert any(i["id"] == "oi-1" for i in op["open_items"])
        assert op["blocking_conditions"]
        auth = _qt(client, "authority")["question_context"]
        assert any(r["artifact_id"] == "art-q" for r in auth["review_history"])
        exp = _qt(client, "exploratory")["question_context"]
        assert exp["contradiction_pairs"]
        # Omitted -> section absent; invalid -> 422.
        plain = client.get("/api/context-object", params={"scope": "doc:ctx-doc"},
                           headers=_auth()).json()
        assert "question_context" not in plain
        bad = client.get("/api/context-object",
                         params={"scope": "doc:ctx-doc", "question_type": "vibes"},
                         headers=_auth())
        assert bad.status_code == 422
        badp = client.post("/api/context-object",
                           json={"scope": {"type": "query", "query": "x"},
                                 "question_type": "vibes"}, headers=_auth())
        assert badp.status_code == 422


def test_historical_tie_warning_and_determinism(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        # Two lineage rows with the SAME timestamp -> total order is approximate (no ordinal).
        dbc.execute("INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts) "
                    "VALUES ('ctx-doc', 'a-doc', 'derives', 7)")
        dbc.execute("INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts) "
                    "VALUES ('ctx-doc', 'b-doc', 'derives', 7)")
        body = _qt(client, "historical")
        assert "trace_order_approximate" in body["scope"]["warnings"]
        for qtype in ("historical", "operational", "authority", "exploratory"):
            a = _qt(client, qtype)
            b = _qt(client, qtype)
            assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), qtype
        # Multi-doc exploratory discloses the neighbors limitation.
        proj = client.get("/api/context-object",
                          params={"scope": "project:CtxProj",
                                  "question_type": "exploratory"}, headers=_auth()).json()
        assert "exploratory_neighbors_doc_scope_only" in proj["scope"]["warnings"]
        assert "neighbors" not in proj["question_context"]


# ── WO-R4: fold-neighborhood retrieval (Level 6, node scope) ─────────────────────


NEIGHBOR_MD = """---
boh:
  id: "{doc_id}"
  title: "{title}"
  status: "draft"
  authority_state: "draft"
  project: "CtxProj"
---

# {title}

Neighbor fixture content with enough words for indexing purposes here.
"""


def _seed_graph(dbc, lib):
    from pathlib import Path
    from app.services.indexer import index_file
    for doc_id, title in (("nbr-b", "Neighbor B"), ("nbr-c", "Neighbor C"),
                          ("old-doc", "Old Doc")):
        p = Path(lib) / f"{doc_id}.md"
        p.write_text(NEIGHBOR_MD.format(doc_id=doc_id, title=title), encoding="utf-8")
        index_file(p, Path(lib))
    dbc.execute("INSERT INTO doc_edges (source_doc_id, target_doc_id, edge_type, detected_ts) "
                "VALUES ('ctx-doc', 'nbr-b', 'derives', 1)")
    dbc.execute("INSERT INTO doc_edges (source_doc_id, target_doc_id, edge_type, detected_ts) "
                "VALUES ('nbr-b', 'nbr-c', 'conflicts', 2)")
    dbc.execute("INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts) "
                "VALUES ('ctx-doc', 'old-doc', 'supersedes', 3)")


def test_node_scope_traversal_radius_and_filter(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        _seed_graph(dbc, lib)
        r1 = client.get("/api/context-object", params={"scope": "node:ctx-doc"},
                        headers=_auth()).json()
        assert r1["state"]["kind"] == "neighborhood"
        assert set(m for m in ("ctx-doc", "nbr-b", "old-doc")) <= {
            e["source"] for e in r1["state"]["edges"]} | {
            e["target"] for e in r1["state"]["edges"]}
        assert r1["scope"]["resolved"]["member_count"] == 3  # radius 1: center + b + old
        r2 = client.get("/api/context-object", params={"scope": "node:ctx-doc", "radius": 2},
                        headers=_auth()).json()
        assert r2["scope"]["resolved"]["member_count"] == 4  # + nbr-c at depth 2
        # Edge-type filter restricted to the verified vocabulary.
        filt = client.get("/api/context-object",
                          params={"scope": "node:ctx-doc", "edge_types": "derives"},
                          headers=_auth()).json()
        assert filt["scope"]["resolved"]["member_count"] == 2  # center + nbr-b only
        assert all(e["type"] == "derives" for e in filt["state"]["edges"])
        bad = client.get("/api/context-object",
                         params={"scope": "node:ctx-doc", "edge_types": "topic_overlap"},
                         headers=_auth())
        assert bad.status_code == 422  # display-only taxonomy is not traversable
        # Determinism.
        a = client.get("/api/context-object", params={"scope": "node:ctx-doc", "radius": 2},
                       headers=_auth()).json()
        assert json.dumps(a, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_node_scope_authority_paths_and_unresolvable(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        _seed_graph(dbc, lib)
        r = client.get("/api/context-object", params={"scope": "node:ctx-doc"},
                       headers=_auth()).json()
        paths = r["state"]["authority_paths"]
        assert any(step["type"] == "supersedes" and step["to"] == "old-doc"
                   for p in paths for step in p)
        contrib = r["state"]["pressure_contributors"]
        assert "connectivity" in contrib and "freshness" in contrib
        # A node with NO authority-bearing edges -> structured unresolvable unknown.
        iso = client.get("/api/context-object", params={"scope": "node:nbr-c"},
                         headers=_auth()).json()
        assert iso["state"]["authority_paths"] == []
        assert any("authority_path_unresolvable" in (u.get("meaning") or "")
                   for u in iso["unknowns"])
        # Unknown node -> scope_not_found, never fabricated traversal.
        missing = client.get("/api/context-object", params={"scope": "node:nope"},
                             headers=_auth()).json()
        assert missing["scope"]["resolved"] is None
        assert "scope_not_found" in missing["scope"]["warnings"]


def test_node_scope_excludes_promoted_neighbors(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        dbc.execute(GHOST)
        dbc.execute("INSERT INTO doc_edges (source_doc_id, target_doc_id, edge_type, "
                    "detected_ts) VALUES ('ctx-doc', 'promoted-ghost', 'derives', 1)")
        closed = client.get("/api/context-object", params={"scope": "node:ctx-doc"},
                            headers=_auth()).json()
        _no_ghost_anywhere(closed)
        assert closed["scope"]["resolved"]["member_count"] == 1
        monkeypatch.setenv("BOH_RETRIEVAL_INCLUDE_PROMOTED", "true")
        opened = client.get("/api/context-object",
                            params={"scope": "node:ctx-doc", "include_promoted": True},
                            headers=_auth()).json()
        assert opened["scope"]["resolved"]["member_count"] == 2  # dual gate open -> visible


def test_post_auth_and_no_mutation_honesty(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, dbc, lib):
        _seed(dbc, lib)
        assert client.post("/api/context-object",
                           json={"scope": {"type": "query", "query": "x"}},
                           headers={"X-BOH-Retrieval-Token": "wrong"}).status_code == 403
        # Advisory honesty: assembling executes NOTHING — durable tables unchanged.
        tables = ("docs", "conflicts", "audit_log", "intake_promotions", "doc_chunks")
        before = {t: dbc.fetchone(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in tables}
        for params in ({"scope": "doc:ctx-doc"}, {"scope": "project:CtxProj"},
                       {"scope": "doc:ctx-doc", "only": "blocking"}):
            assert client.get("/api/context-object", params=params,
                              headers=_auth()).status_code == 200
        after = {t: dbc.fetchone(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in tables}
        assert after == before

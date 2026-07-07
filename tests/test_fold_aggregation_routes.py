"""tests/test_fold_aggregation_routes.py -- Phase 7b cluster/corpus routes.

Covers the read-only aggregation routes that resolve membership from the live
DB and feed the frozen Phase 7a engine (project + plane axes only):

  - GET /api/fold/cluster/{axis}/{value}
  - GET /api/fold/corpus/{axis}
  - GET /api/fold/cluster/{axis}/{value}/trace  (lazy stub)

Governance invariants checked:
  - project membership matches docs.project exactly
  - scope_id round-trips from a node's Phase 6 scale_actions target_id
  - corpus scope shape (corpus:{axis})
  - unsupported axis -> HTTP 400, never 500
  - empty cluster -> 200 empty_cluster packet (not 404)
  - canon_eligible never true; scores_are_truth_values false
  - aggregate trace stub returns available:false
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test client fixture (mirrors test_fold_scale_actions.py)
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

    import app.core.auth as auth
    import app.api.main as main
    importlib.reload(auth)
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db, library


def _insert_doc(db, doc_id: str, title: str = "Test Doc",
                authority_state: str = "reviewed", project: str | None = None) -> None:
    if project is None:
        db.execute(
            """INSERT OR IGNORE INTO docs (doc_id, title, path, authority_state)
               VALUES (?, ?, ?, ?)""",
            (doc_id, title, f"/library/{doc_id}.md", authority_state),
        )
    else:
        db.execute(
            """INSERT OR IGNORE INTO docs (doc_id, title, path, authority_state, project)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, title, f"/library/{doc_id}.md", authority_state, project),
        )


# ---------------------------------------------------------------------------
# Cluster route -- project axis (membership resolvable from docs.project)
# ---------------------------------------------------------------------------

class TestProjectClusterRoute:
    def test_cluster_scope_shape(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            _insert_doc(db, "p2", project="boh")
            r = client.get("/api/fold/cluster/project/boh")
            assert r.status_code == 200
            body = r.json()
            assert body["scope"]["scale"] == "cluster"
            assert body["scope"]["scope_id"] == "project:boh"
            assert body["scope"]["axis"] == "project"
            assert body["scope"]["axis_value"] == "boh"

    def test_membership_matches_docs_project(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "in1", project="boh")
            _insert_doc(db, "in2", project="boh")
            _insert_doc(db, "out1", project="other")
            r = client.get("/api/fold/cluster/project/boh")
            body = r.json()
            assert body["aggregation"]["inputs_count"] == 2
            scope_ids = {c["scope_id"] for c in body["contributors"]}
            assert scope_ids == {"in1", "in2"}

    def test_unknown_value_is_empty_cluster(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            r = client.get("/api/fold/cluster/project/does_not_exist")
            assert r.status_code == 200
            body = r.json()
            assert body["aggregation"]["inputs_count"] == 0
            assert body["symbolic_state"]["currentness_label"] == "unknown"
            assert any(u["field"] == "empty_cluster" for u in body["unknowns"])

    def test_null_project_doc_registers_ambiguous(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            # docs.project carries a default, so force an explicit NULL to exercise
            # the membership-ambiguous path.
            db.execute(
                """INSERT OR IGNORE INTO docs (doc_id, title, path, authority_state, project)
                   VALUES (?, ?, ?, ?, NULL)""",
                ("p2", "Test Doc", "/library/p2.md", "reviewed"),
            )
            r = client.get("/api/fold/cluster/project/boh")
            body = r.json()
            # The boh cluster has one real member; the null-project doc is not a
            # silent member -- it surfaces as cluster_membership_ambiguous.
            assert body["aggregation"]["inputs_count"] == 1
            assert any(
                u["field"] == "cluster_membership_ambiguous" for u in body["unknowns"]
            )

    def test_canon_eligible_never_true(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh", authority_state="canonical")
            r = client.get("/api/fold/cluster/project/boh")
            body = r.json()
            assert body["canon_eligible"] is False
            assert body["scalar_state"]["scores_are_truth_values"] is False

    def test_scope_id_round_trip_from_scale_action(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            node = client.get("/api/fold/node/p1").json()
            proj = [
                a for a in node["scale_actions"]
                if a["target_axis"] == "project" and a["allowed"]
            ]
            assert proj, "expected an allowed project scale_action"
            axis, value = proj[0]["target_id"].split(":", 1)
            r = client.get(f"/api/fold/cluster/{axis}/{value}")
            assert r.status_code == 200
            assert r.json()["scope"]["scope_id"] == proj[0]["target_id"]


# ---------------------------------------------------------------------------
# Corpus route
# ---------------------------------------------------------------------------

class TestCorpusRoute:
    def test_project_corpus_scope_shape(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            _insert_doc(db, "p2", project="other")
            r = client.get("/api/fold/corpus/project")
            assert r.status_code == 200
            body = r.json()
            assert body["scope"]["scale"] == "corpus"
            assert body["scope"]["scope_id"] == "corpus:project"

    def test_corpus_aggregates_clusters(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            _insert_doc(db, "p2", project="other")
            r = client.get("/api/fold/corpus/project")
            body = r.json()
            # Two distinct projects -> two cluster contributors at corpus scale.
            assert body["aggregation"]["inputs_count"] == 2
            assert body["canon_eligible"] is False

    def test_plane_corpus_returns_packet(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            r = client.get("/api/fold/corpus/plane")
            assert r.status_code == 200
            assert r.json()["scope"]["scope_id"] == "corpus:plane"


# ---------------------------------------------------------------------------
# Plane axis route (membership resolved from the node packet)
# ---------------------------------------------------------------------------

class TestPlaneClusterRoute:
    def test_plane_cluster_returns_packet(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            r = client.get("/api/fold/cluster/plane/authority")
            assert r.status_code == 200
            body = r.json()
            assert body["scope"]["scale"] == "cluster"
            assert body["scope"]["scope_id"] == "plane:authority"
            assert body["canon_eligible"] is False


# ---------------------------------------------------------------------------
# Unsupported axes -> 400 (truly unknown axis)
# ---------------------------------------------------------------------------

class TestUnsupportedAxes:
    def test_unknown_axis_cluster_is_400(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            r = client.get("/api/fold/cluster/galaxy/milkyway")
            assert r.status_code == 400
            assert "galaxy" in r.json()["detail"]

    def test_unknown_axis_corpus_is_400(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            r = client.get("/api/fold/corpus/galaxy")
            assert r.status_code == 400


# ---------------------------------------------------------------------------
# Domain axis -- schema-gap semantics
# ---------------------------------------------------------------------------

def _insert_lattice_domain(db, domain: str, label: str = "Test Domain") -> None:
    db.execute(
        """INSERT OR IGNORE INTO substrate_lattice_registry
           (lattice_id, domain, label, created_at)
           VALUES (?, ?, ?, ?)""",
        (f"SL_{domain}", domain, label, "2026-01-01T00:00:00+00:00"),
    )


def _link_doc_topic(db, doc_id: str, topics: str) -> None:
    db.execute("UPDATE docs SET topics_tokens = ? WHERE doc_id = ?", (topics, doc_id))


def _insert_card_topic(db, doc_id: str, topic: str, payload_topics: str = "") -> None:
    import json
    db.execute(
        """INSERT OR REPLACE INTO cards
           (id, plane, card_type, topic, b, d, m, payload_json, doc_id, created_ts, updated_ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            f"CARD:{doc_id}",
            "informational",
            "source_document",
            topic,
            0,
            0,
            "contain",
            json.dumps({"topics": payload_topics}),
            doc_id,
            1,
            1,
        ),
    )


class TestDomainClusterRoute:
    def test_domain_cluster_returns_200_not_400(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            r = client.get("/api/fold/cluster/domain/clinical")
            assert r.status_code == 200

    def test_domain_cluster_scope_shape(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            body = client.get("/api/fold/cluster/domain/clinical").json()
            assert body["scope"]["scale"] == "cluster"
            assert body["scope"]["scope_id"] == "domain:clinical"
            assert body["scope"]["axis"] == "domain"

    def test_domain_cluster_has_zero_members_when_no_doc_matches(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_lattice_domain(db, "clinical")
            _insert_doc(db, "p1", project="boh")
            body = client.get("/api/fold/cluster/domain/clinical").json()
            assert body["aggregation"]["inputs_count"] == 0

    def test_domain_cluster_uses_indexed_topic_membership(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_lattice_domain(db, "clinical")
            _insert_doc(db, "p1", project="boh")
            _insert_doc(db, "p2", project="boh")
            _link_doc_topic(db, "p1", "clinical")
            body = client.get("/api/fold/cluster/domain/clinical").json()
            assert body["aggregation"]["inputs_count"] == 1
            assert {c["scope_id"] for c in body["contributors"]} == {"p1"}
            fields = [u["field"] for u in body["unknowns"]]
            assert "domain_membership_unresolvable" not in fields

    def test_domain_cluster_uses_planecard_topic_membership(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_lattice_domain(db, "clinical")
            _insert_doc(db, "p1", project="boh")
            _insert_card_topic(db, "p1", "Clinical")
            body = client.get("/api/fold/cluster/domain/clinical").json()
            assert body["aggregation"]["inputs_count"] == 1
            assert {c["scope_id"] for c in body["contributors"]} == {"p1"}

    def test_domain_cluster_not_diagnostic_only_after_linkage(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_lattice_domain(db, "clinical")
            body = client.get("/api/fold/cluster/domain/clinical").json()
            assert body["aggregation"]["diagnostic_only"] is False

    def test_domain_cluster_canon_eligible_never_true(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            body = client.get("/api/fold/cluster/domain/clinical").json()
            assert body["canon_eligible"] is False

    def test_domain_corpus_empty_registry_returns_200(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            r = client.get("/api/fold/corpus/domain")
            assert r.status_code == 200
            body = r.json()
            assert body["scope"]["scope_id"] == "corpus:domain"
            assert body["aggregation"]["inputs_count"] == 0

    def test_domain_corpus_empty_registry_has_empty_cluster_unknown(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            body = client.get("/api/fold/corpus/domain").json()
            fields = [u["field"] for u in body["unknowns"]]
            assert "empty_cluster" in fields
            assert "domain_membership_unresolvable" not in fields

    def test_domain_corpus_with_registered_domains_returns_one_cluster_per_domain(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_lattice_domain(db, "clinical")
            _insert_lattice_domain(db, "engineering")
            body = client.get("/api/fold/corpus/domain").json()
            # Two domains -> two cluster contributors at corpus scale
            assert body["aggregation"]["inputs_count"] == 2

    def test_domain_corpus_with_linked_domain_has_cluster_contributor(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_lattice_domain(db, "clinical")
            _insert_doc(db, "p1", project="boh")
            _link_doc_topic(db, "p1", "clinical")
            body = client.get("/api/fold/corpus/domain").json()
            assert body["aggregation"]["inputs_count"] == 1
            assert {c["scope_id"] for c in body["contributors"]} == {"domain:clinical"}

    def test_blank_domain_excluded_from_corpus(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            # Insert a blank-domain row — should be excluded from enumeration
            db.execute(
                """INSERT OR IGNORE INTO substrate_lattice_registry
                   (lattice_id, domain, label, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("SL_blank", "   ", "Blank Domain", "2026-01-01T00:00:00+00:00"),
            )
            body = client.get("/api/fold/corpus/domain").json()
            # Blank domain must not appear as a cluster
            assert body["aggregation"]["inputs_count"] == 0


# ---------------------------------------------------------------------------
# Batch axis -- intake_capabilities membership
# ---------------------------------------------------------------------------

def _insert_intake_cap(db, doc_id: str, batch_id: str, source_ref: str | None = None) -> None:
    if source_ref is None:
        source_ref = f"/library/{doc_id}.md"
    db.execute(
        """INSERT OR IGNORE INTO intake_capabilities
           (intake_capability_id, source_ref, batch_id, created_at)
           VALUES (?, ?, ?, ?)""",
        (f"IC_{doc_id}_{batch_id}", source_ref, batch_id, "2026-01-01T00:00:00+00:00"),
    )


class TestBatchClusterRoute:
    def test_batch_cluster_returns_200_not_400(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            r = client.get("/api/fold/cluster/batch/b123")
            assert r.status_code == 200

    def test_batch_cluster_scope_shape(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            body = client.get("/api/fold/cluster/batch/b123").json()
            assert body["scope"]["scope_id"] == "batch:b123"
            assert body["scope"]["axis"] == "batch"

    def test_batch_cluster_empty_when_no_intake_records(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            body = client.get("/api/fold/cluster/batch/b123").json()
            assert body["aggregation"]["inputs_count"] == 0

    def test_batch_cluster_doc_with_matching_source_ref_is_member(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1")
            _insert_intake_cap(db, "p1", "batch-A", "/library/p1.md")
            body = client.get("/api/fold/cluster/batch/batch-A").json()
            assert body["aggregation"]["inputs_count"] == 1
            scope_ids = {c["scope_id"] for c in body["contributors"]}
            assert "p1" in scope_ids

    def test_batch_cluster_deduplicates_multiple_intake_rows(self, tmp_path, monkeypatch):
        """Two intake records for the same source_ref + batch must not inflate inputs_count."""
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1")
            # Insert two rows for the same path + batch
            db.execute(
                """INSERT OR IGNORE INTO intake_capabilities
                   (intake_capability_id, source_ref, batch_id, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("IC_p1_bA_1", "/library/p1.md", "batch-A", "2026-01-01T00:00:00+00:00"),
            )
            db.execute(
                """INSERT OR IGNORE INTO intake_capabilities
                   (intake_capability_id, source_ref, batch_id, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("IC_p1_bA_2", "/library/p1.md", "batch-A", "2026-01-02T00:00:00+00:00"),
            )
            body = client.get("/api/fold/cluster/batch/batch-A").json()
            assert body["aggregation"]["inputs_count"] == 1

    def test_batch_cluster_doc_in_multiple_batches_appears_in_each(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1")
            _insert_intake_cap(db, "p1", "batch-A", "/library/p1.md")
            _insert_intake_cap(db, "p1_b", "batch-B", "/library/p1.md")
            body_a = client.get("/api/fold/cluster/batch/batch-A").json()
            body_b = client.get("/api/fold/cluster/batch/batch-B").json()
            assert body_a["aggregation"]["inputs_count"] == 1
            assert body_b["aggregation"]["inputs_count"] == 1

    def test_batch_cluster_doc_without_intake_registers_ambiguous(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            # Doc with no intake record at all
            _insert_doc(db, "p1")
            body = client.get("/api/fold/cluster/batch/batch-A").json()
            assert any(u["field"] == "cluster_membership_ambiguous" for u in body["unknowns"])

    def test_batch_cluster_diagnostic_only(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            body = client.get("/api/fold/cluster/batch/b123").json()
            assert body["aggregation"]["diagnostic_only"] is True

    def test_batch_cluster_intake_record_no_matching_doc_does_not_crash(self, tmp_path, monkeypatch):
        """An intake record whose source_ref has no matching docs.path must not crash."""
        with _client(tmp_path, monkeypatch) as (client, db, _):
            # Insert intake record with path that has no doc
            db.execute(
                """INSERT OR IGNORE INTO intake_capabilities
                   (intake_capability_id, source_ref, batch_id, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("IC_orphan", "/library/orphan.md", "batch-X", "2026-01-01T00:00:00+00:00"),
            )
            r = client.get("/api/fold/cluster/batch/batch-X")
            assert r.status_code == 200
            assert r.json()["aggregation"]["inputs_count"] == 0

    def test_batch_corpus_empty_returns_200(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            r = client.get("/api/fold/corpus/batch")
            assert r.status_code == 200
            body = r.json()
            assert body["scope"]["scope_id"] == "corpus:batch"
            assert body["aggregation"]["inputs_count"] == 0

    def test_batch_corpus_two_batches_two_clusters(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1")
            _insert_doc(db, "p2")
            _insert_intake_cap(db, "p1", "batch-A", "/library/p1.md")
            _insert_intake_cap(db, "p2b", "batch-B", "/library/p2.md")
            body = client.get("/api/fold/corpus/batch").json()
            assert body["aggregation"]["inputs_count"] == 2

    def test_blank_batch_id_excluded_from_corpus(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            db.execute(
                """INSERT OR IGNORE INTO intake_capabilities
                   (intake_capability_id, source_ref, batch_id, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("IC_blank", "/library/p1.md", "  ", "2026-01-01T00:00:00+00:00"),
            )
            body = client.get("/api/fold/corpus/batch").json()
            assert body["aggregation"]["inputs_count"] == 0

    def test_batch_cluster_canon_eligible_never_true(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", authority_state="canonical")
            _insert_intake_cap(db, "p1", "batch-A", "/library/p1.md")
            body = client.get("/api/fold/cluster/batch/batch-A").json()
            assert body["canon_eligible"] is False


class TestAggregateTraceStub:
    def test_cluster_trace_stub(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "p1", project="boh")
            r = client.get("/api/fold/cluster/project/boh/trace")
            assert r.status_code == 200
            body = r.json()
            assert body["available"] is False
            assert body["scope_id"] == "project:boh"
            assert body["compact_trace_ref"] == "/api/fold/cluster/project/boh"

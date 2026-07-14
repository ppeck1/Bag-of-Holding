"""Migration-gate tests for DRAFT migration 0002_intake_retrieval_promotion (WO-2).

DRAFTED 2026-06-10 for the owner schema-review package. The module-level guard below skips the
whole file while the migration is drafted-but-unwired (DEC-0002: no implementation without owner
schema approval). When the owner approves and `MIGRATION` is appended to
`app.db.migrations.MIGRATIONS`, these tests activate automatically — no edit needed.

Covers: schema shape, ledger idempotency, fail-loud on pre-existing table, the partial-unique
single-active-promotion winner, demotion CHECK constraints, and the DEC-0003 provenance case —
a fingerprint-era capability resolving through its handoff to an OLDER content-identical
artifact identity without losing the new capability -> run -> source-revision chain.
"""

import sqlite3
import uuid

import pytest

from app.db import migrations as migrations_mod
from app.db.migrations_0002_intake_retrieval_promotion import MIGRATION
from app.db.migrations_0001_intake_orchestration_integrity import MIGRATION as MIGRATION_0001

if MIGRATION.id not in {m.id for m in migrations_mod.MIGRATIONS}:
    pytest.skip(
        "migration 0002 is DRAFTED but not wired into MIGRATIONS (awaiting owner schema approval)",
        allow_module_level=True,
    )


@pytest.fixture()
def conn(tmp_path):
    """Temp DB with 0001 + 0002 applied through the real runner (never the real boh.db)."""
    db_path = tmp_path / "boh_0002_gate.db"

    def factory():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    migrations_mod.run_migrations(
        factory, str(db_path), [MIGRATION_0001, MIGRATION], backup=False
    )
    c = factory()
    c.execute("PRAGMA foreign_keys = ON")
    # Minimal stand-ins for the NON-migration-managed parents (baseline/Phase-7 layer) so the
    # dangling-reference DETECTION queries (lineage matrix: informational-posture identifiers)
    # can be exercised at schema level.
    c.execute("CREATE TABLE intake_capabilities (intake_capability_id TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE intake_normalized_artifacts (normalized_artifact_id TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE docs (doc_id TEXT PRIMARY KEY)")
    yield c
    c.close()


def _cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _indexes(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA index_list({table})")}


T = "2026-06-10T00:00:00Z"


def _insert_revision(conn, srid, ref, content_hash, adapter_version):
    conn.execute(
        "INSERT INTO intake_source_revisions (source_revision_id, canonical_source_ref, "
        "source_hash_sha256, byte_size, policy_snapshot_hash, adapter_registry_version, "
        "lifecycle_state, created_at, last_seen_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (srid, ref, content_hash, 10, "policy-unbound-v1", adapter_version,
         "complete", T, T, T),
    )


def _insert_run(conn, run_id, srid, cap_id):
    conn.execute(
        "INSERT INTO intake_runs (run_id, source_revision_id, source_ref_snapshot, "
        "intake_capability_id, trigger_kind, lifecycle_state, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (run_id, srid, "b:/x", cap_id, "scheduler", "complete", T, T),
    )


def _insert_handoff(conn, hid, cap_id, run_id, srid, artifact_id, ready=1, profile=None):
    conn.execute(
        "INSERT INTO intake_handoffs (handoff_id, intake_capability_id, intake_run_id, "
        "source_revision_id, normalized_artifact_id, handoff_ready, handoff_at, adapter_id, "
        "adapter_version, adapter_registry_version, policy_snapshot_hash, "
        "normalized_output_type, normalized_output_profile, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (hid, cap_id, run_id, srid, artifact_id, ready, T, "markdown_direct", "1.0",
         "adapterfp-v1:abc", "policy-unbound-v1", "markdown", profile, T),
    )


def _insert_promotion(conn, pid, srid, cap_id, hid, artifact_id, doc_id, status="active",
                      demoted_by=None, demoted_at=None, batch="batch-1", profile=None,
                      supersedes=None):
    conn.execute(
        "INSERT INTO intake_promotions (promotion_id, promotion_batch_id, source_revision_id, "
        "intake_capability_id, handoff_id, normalized_artifact_id, doc_id, normalized_hash, "
        "normalized_output_type, normalized_output_profile, adapter_id, adapter_version, "
        "adapter_registry_version, policy_snapshot_hash, status, supersedes_promotion_id, "
        "promoted_by, promoted_at, demoted_by, demoted_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, batch, srid, cap_id, hid, artifact_id, doc_id, "nh", "markdown", profile,
         "markdown_direct", "1.0", "adapterfp-v1:abc", "policy-unbound-v1", status, supersedes,
         "local_operator", T, demoted_by, demoted_at, T),
    )


def _seed_chain(conn, srid="srid-a", run_id="run-1", cap_id="cap-1", hid="h-1",
                artifact_id="na-1"):
    """Revision + run + handoff so promotion FKs are satisfiable."""
    _insert_revision(conn, srid, "b:/x", "h1", "adapterfp-v1:abc")
    _insert_run(conn, run_id, srid, cap_id)
    _insert_handoff(conn, hid, cap_id, run_id, srid, artifact_id)


class TestSchemaShape:
    def test_both_ledgers_exist_with_expected_columns(self, conn):
        assert _cols(conn, "intake_handoffs") == {
            "handoff_id", "intake_capability_id", "intake_run_id", "source_revision_id",
            "normalized_artifact_id", "handoff_ready", "handoff_at", "adapter_id",
            "adapter_version", "adapter_registry_version", "policy_snapshot_hash",
            "normalized_output_type", "normalized_output_profile", "warnings_json", "created_at",
        }
        assert _cols(conn, "intake_promotions") == {
            "promotion_id", "promotion_batch_id", "source_revision_id", "intake_capability_id",
            "handoff_id", "normalized_artifact_id", "doc_id", "normalized_hash",
            "normalized_output_type", "normalized_output_profile", "adapter_id",
            "adapter_version", "adapter_registry_version", "policy_snapshot_hash", "status",
            "supersedes_promotion_id", "promoted_by", "promoted_at", "demoted_by",
            "demoted_at", "updated_at",
        }

    def test_expected_indexes_present(self, conn):
        assert {"idx_intake_handoffs_capability", "idx_intake_handoffs_revision",
                "idx_intake_handoffs_ready_created"} <= _indexes(conn, "intake_handoffs")
        assert {"idx_intake_promotions_active_revision", "idx_intake_promotions_doc",
                "idx_intake_promotions_status_promoted",
                "idx_intake_promotions_handoff"} <= _indexes(conn, "intake_promotions")

    def test_second_run_is_ledger_noop(self, conn, tmp_path):
        db_path = tmp_path / "boh_0002_gate.db"

        def factory():
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            return c

        result = migrations_mod.run_migrations(
            factory, str(db_path), [MIGRATION_0001, MIGRATION], backup=False)
        assert result["applied"] == []

    def test_unexpected_preexisting_table_fails_loudly(self, tmp_path):
        db_path = tmp_path / "dirty.db"
        c = sqlite3.connect(db_path)
        c.execute("CREATE TABLE intake_promotions (x TEXT)")
        c.commit()
        c.close()

        def factory():
            cc = sqlite3.connect(db_path)
            cc.row_factory = sqlite3.Row
            return cc

        with pytest.raises(Exception):
            migrations_mod.run_migrations(
                factory, str(db_path), [MIGRATION_0001, MIGRATION], backup=False)


class TestPromotionInvariants:
    def test_single_active_promotion_per_revision(self, conn):
        _seed_chain(conn)
        _insert_promotion(conn, "p1", "srid-a", "cap-1", "h-1", "na-1", "doc-1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_promotion(conn, "p2", "srid-a", "cap-1", "h-1", "na-1", "doc-2")

    def test_superseded_and_demoted_rows_do_not_block_new_active(self, conn):
        _seed_chain(conn)
        _insert_promotion(conn, "p1", "srid-a", "cap-1", "h-1", "na-1", "doc-1",
                          status="demoted", demoted_by="op", demoted_at=T)
        _insert_promotion(conn, "p2", "srid-a", "cap-1", "h-1", "na-1", "doc-2")  # ok

    def test_demotion_fields_all_or_none(self, conn):
        _seed_chain(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_promotion(conn, "p1", "srid-a", "cap-1", "h-1", "na-1", "doc-1",
                              status="demoted", demoted_by=None, demoted_at=T)

    def test_demoted_status_requires_demoted_at(self, conn):
        _seed_chain(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_promotion(conn, "p1", "srid-a", "cap-1", "h-1", "na-1", "doc-1",
                              status="demoted")

    def test_handoff_fk_requires_known_revision(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            _insert_handoff(conn, "h-x", "cap-x", "run-x", "srid-missing", "na-x")

    def test_promotion_batch_id_is_nullable_grouping_metadata(self, conn):
        # DEC-0004.4: batch is grouping metadata only; a promotion stands alone without one.
        _seed_chain(conn)
        _insert_promotion(conn, "p1", "srid-a", "cap-1", "h-1", "na-1", "doc-1", batch=None)
        row = conn.execute(
            "SELECT promotion_batch_id, status FROM intake_promotions "
            "WHERE promotion_id='p1'").fetchone()
        assert row["promotion_batch_id"] is None
        assert row["status"] == "active"

    def test_normalized_output_profile_nullable_and_storable(self, conn):
        # DEC-0004.2: explicit neutralized-HTML classification lives in the DEDICATED ledger
        # profile column; core artifact output_type is never overloaded.
        _seed_chain(conn)
        _insert_handoff(conn, "h-html", "cap-1", "run-1", "srid-a", "na-1",
                        profile="html_neutralized_markdown")
        _insert_promotion(conn, "p1", "srid-a", "cap-1", "h-html", "na-1", "doc-1",
                          profile="html_neutralized_markdown")
        h = conn.execute("SELECT normalized_output_type, normalized_output_profile "
                         "FROM intake_handoffs WHERE handoff_id='h-html'").fetchone()
        p = conn.execute("SELECT normalized_output_type, normalized_output_profile "
                         "FROM intake_promotions WHERE promotion_id='p1'").fetchone()
        assert h["normalized_output_type"] == "markdown"          # artifact-level representation
        assert h["normalized_output_profile"] == "html_neutralized_markdown"
        assert p["normalized_output_profile"] == "html_neutralized_markdown"
        plain = conn.execute("SELECT normalized_output_profile FROM intake_handoffs "
                             "WHERE handoff_id='h-1'").fetchone()
        assert plain["normalized_output_profile"] is None         # non-HTML rows stay NULL


class TestLineageEnforcement:
    """Per-identifier enforcement posture (review package Â§2b matrix)."""

    def test_handoff_fk_requires_known_run(self, conn):
        _insert_revision(conn, "srid-a", "b:/x", "h1", "adapterfp-v1:abc")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_handoff(conn, "h-x", "cap-1", "run-missing", "srid-a", "na-1")

    def test_promotion_fk_requires_known_handoff(self, conn):
        _insert_revision(conn, "srid-a", "b:/x", "h1", "adapterfp-v1:abc")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_promotion(conn, "p1", "srid-a", "cap-1", "h-missing", "na-1", "doc-1")

    def test_supersedes_fk_requires_known_promotion(self, conn):
        _seed_chain(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_promotion(conn, "p1", "srid-a", "cap-1", "h-1", "na-1", "doc-1",
                              supersedes="p-missing")

    def test_dangling_capability_artifact_doc_are_detectable(self, conn):
        # Informational-posture identifiers: SQLite deliberately does NOT enforce these
        # (non-migration-managed parents). The detection queries below are the documented
        # invariant checks the promotion runtime and audit gates must run.
        _insert_revision(conn, "srid-a", "b:/x", "h1", "adapterfp-v1:abc")
        _insert_run(conn, "run-1", "srid-a", "cap-ghost")
        _insert_handoff(conn, "h-1", "cap-ghost", "run-1", "srid-a", "na-ghost")
        _insert_promotion(conn, "p1", "srid-a", "cap-ghost", "h-1", "na-ghost", "doc-ghost")

        dangling_caps = conn.execute(
            "SELECT h.handoff_id FROM intake_handoffs h "
            "LEFT JOIN intake_capabilities c ON c.intake_capability_id = h.intake_capability_id "
            "WHERE c.intake_capability_id IS NULL").fetchall()
        dangling_artifacts = conn.execute(
            "SELECT h.handoff_id FROM intake_handoffs h "
            "LEFT JOIN intake_normalized_artifacts n "
            "ON n.normalized_artifact_id = h.normalized_artifact_id "
            "WHERE n.normalized_artifact_id IS NULL").fetchall()
        dangling_docs = conn.execute(
            "SELECT p.promotion_id FROM intake_promotions p "
            "LEFT JOIN docs d ON d.doc_id = p.doc_id "
            "WHERE d.doc_id IS NULL").fetchall()
        assert [r["handoff_id"] for r in dangling_caps] == ["h-1"]
        assert [r["handoff_id"] for r in dangling_artifacts] == ["h-1"]
        assert [r["promotion_id"] for r in dangling_docs] == ["p1"]

        # And the same queries return clean when the parents exist.
        conn.execute("INSERT INTO intake_capabilities VALUES ('cap-ghost')")
        conn.execute("INSERT INTO intake_normalized_artifacts VALUES ('na-ghost')")
        conn.execute("INSERT INTO docs VALUES ('doc-ghost')")
        assert conn.execute(
            "SELECT COUNT(*) FROM intake_handoffs h "
            "LEFT JOIN intake_capabilities c ON c.intake_capability_id = h.intake_capability_id "
            "WHERE c.intake_capability_id IS NULL").fetchone()[0] == 0


class TestDec0003ProvenanceCase:
    """A fingerprint-era capability resolves through its handoff to an OLDER content-identical
    artifact identity without losing the new capability -> run -> source-revision chain."""

    def test_fingerprint_era_handoff_resolves_to_older_artifact(self, conn):
        content_hash = "deadbeef" * 8
        # Era 1 (sentinel): original revision; the artifact row is minted in THIS era.
        _insert_revision(conn, "srid-old", "x:/fixtures/canon/1/doc.md", content_hash,
                         "adapter-registry-unversioned-v1")
        _insert_run(conn, "run-old", "srid-old", "cap-old")
        old_artifact_id = "na_" + uuid.uuid4().hex[:12]  # created during era 1

        # Era 2 (fingerprint): SAME bytes -> NEW revision identity, NEW run, NEW capability;
        # artifact identity converges (DEC-0003) so the handoff references the era-1 artifact.
        _insert_revision(conn, "srid-new", "x:/fixtures/canon/1/doc.md", content_hash,
                         "adapterfp-v1:688fdf4f")
        _insert_run(conn, "run-new", "srid-new", "cap-new")
        _insert_handoff(conn, "h-new", "cap-new", "run-new", "srid-new", old_artifact_id)

        row = conn.execute(
            """
            SELECT h.intake_capability_id, h.intake_run_id, h.normalized_artifact_id,
                   r.source_revision_id, r.adapter_registry_version, r.source_hash_sha256,
                   run.trigger_kind, run.lifecycle_state
            FROM intake_handoffs h
            JOIN intake_source_revisions r ON r.source_revision_id = h.source_revision_id
            JOIN intake_runs run ON run.run_id = h.intake_run_id
            WHERE h.handoff_id = 'h-new'
            """
        ).fetchone()
        # New-era chain fully preserved...
        assert row["intake_capability_id"] == "cap-new"
        assert row["intake_run_id"] == "run-new"
        assert row["source_revision_id"] == "srid-new"
        assert row["adapter_registry_version"] == "adapterfp-v1:688fdf4f"
        assert row["lifecycle_state"] == "complete"
        # ...while the artifact identity is the OLDER, content-identical one.
        assert row["normalized_artifact_id"] == old_artifact_id
        # And content identity provably converges across the eras.
        old = conn.execute(
            "SELECT source_hash_sha256 FROM intake_source_revisions "
            "WHERE source_revision_id = 'srid-old'").fetchone()
        assert old["source_hash_sha256"] == row["source_hash_sha256"]

    def test_promotion_of_fingerprint_era_handoff_keeps_full_chain(self, conn):
        content_hash = "cafef00d" * 8
        _insert_revision(conn, "srid-new", "x:/fixtures/canon/1/doc2.md", content_hash,
                         "adapterfp-v1:688fdf4f")
        _insert_run(conn, "run-new", "srid-new", "cap-new")
        _insert_handoff(conn, "h-new", "cap-new", "run-new", "srid-new", "na-era1")
        _insert_promotion(conn, "p-new", "srid-new", "cap-new", "h-new", "na-era1", "doc-77")

        row = conn.execute(
            """
            SELECT p.doc_id, p.normalized_artifact_id, p.status,
                   h.intake_run_id, h.intake_capability_id, r.adapter_registry_version
            FROM intake_promotions p
            JOIN intake_handoffs h ON h.handoff_id = p.handoff_id
            JOIN intake_source_revisions r ON r.source_revision_id = p.source_revision_id
            WHERE p.promotion_id = 'p-new'
            """
        ).fetchone()
        assert row["doc_id"] == "doc-77"
        assert row["normalized_artifact_id"] == "na-era1"      # older, content-identical artifact
        assert row["intake_capability_id"] == "cap-new"        # new-era capability preserved
        assert row["intake_run_id"] == "run-new"               # new-era run preserved
        assert row["adapter_registry_version"].startswith("adapterfp-v1:")
        assert row["status"] == "active"

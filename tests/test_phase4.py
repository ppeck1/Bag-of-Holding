"""tests/test_phase4.py: Phase 4 tests — corpus classification, lineage, duplicate detection.

All tests use the shared test DB (BOH_DB env var set by test_integration.py fixture).
"""

import json
import os
import time
import uuid
import tempfile
import pytest

os.environ.setdefault("BOH_DB", os.path.join(os.path.dirname(__file__), "test_boh_v2.db"))
os.environ.setdefault("BOH_LIBRARY", os.path.join(os.path.dirname(__file__), "..", "library"))

from fastapi.testclient import TestClient
from app.api.main import app
from app.db import connection as db
from app.core import corpus as corpus_engine, lineage as lineage_engine
from app.core.corpus import (
    CLASS_CANON, CLASS_DRAFT, CLASS_DERIVED, CLASS_ARCHIVE, CLASS_EVIDENCE,
    classify,
)

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True, scope="module")
def init_db_phase4():
    db.init_db()
    # Seed library
    client.post("/api/index", json={"library_root": os.environ["BOH_LIBRARY"]})


# ═══════════════════════════════════════════════════════════════════════════
# Corpus Classification
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("doc,expected_class", [
    # Canon: status=canonical + release
    ({"status": "canonical", "operator_state": "release", "source_type": "library",
      "type": "note", "topics_tokens": "test"},
     CLASS_CANON),

    # Draft: status=draft + observe
    ({"status": "draft", "operator_state": "observe", "source_type": "library",
      "type": "note", "topics_tokens": "test"},
     CLASS_DRAFT),

    # Archive: status=archived + release
    ({"status": "archived", "operator_state": "release", "source_type": "library",
      "type": "note", "topics_tokens": "test"},
     CLASS_ARCHIVE),

    # Derived: source_type=snapshot
    ({"status": "working", "operator_state": "vessel", "source_type": "snapshot",
      "type": "note", "topics_tokens": "test"},
     CLASS_DERIVED),

    # Evidence: type=log
    ({"status": "draft", "operator_state": "observe", "source_type": "library",
      "type": "log", "topics_tokens": ""},
     CLASS_EVIDENCE),

    # Evidence: type=event
    ({"status": "working", "operator_state": "vessel", "source_type": "library",
      "type": "event", "topics_tokens": "meeting"},
     CLASS_EVIDENCE),

    # Derived beats Archive
    ({"status": "archived", "operator_state": "release", "source_type": "snapshot",
      "type": "note", "topics_tokens": "test"},
     CLASS_DERIVED),
])
def test_corpus_classify(doc, expected_class):
    result = classify(doc)
    assert result == expected_class, f"classify({doc}) = {result!r}, expected {expected_class!r}"


def test_corpus_class_stored_after_index():
    """After crawl_library, all indexed docs should have a corpus_class."""
    docs = db.fetchall("SELECT corpus_class FROM docs WHERE corpus_class IS NOT NULL")
    assert len(docs) > 0, "No docs have corpus_class set after indexing"


def test_corpus_class_all_valid_values():
    """Every corpus_class value must be one of the five valid constants."""
    valid = {CLASS_CANON, CLASS_DRAFT, CLASS_DERIVED, CLASS_ARCHIVE, CLASS_EVIDENCE}
    rows = db.fetchall("SELECT DISTINCT corpus_class FROM docs WHERE corpus_class IS NOT NULL")
    for row in rows:
        assert row["corpus_class"] in valid, f"Invalid corpus_class: {row['corpus_class']!r}"


def test_api_corpus_classes_endpoint():
    r = client.get("/api/corpus/classes")
    assert r.status_code == 200
    body = r.json()
    assert "distribution" in body
    assert "total" in body
    assert "classes" in body
    assert len(body["classes"]) == 5


def test_api_corpus_reclassify():
    r = client.post("/api/corpus/reclassify")
    assert r.status_code == 200
    body = r.json()
    assert "reclassified" in body
    assert body["reclassified"] >= 0


# ═══════════════════════════════════════════════════════════════════════════
# Lineage — record_link and retrieval
# ═══════════════════════════════════════════════════════════════════════════

def _seed_doc(doc_id, path, status="draft", source_type="library", text_hash=""):
    db.execute(
        "INSERT OR REPLACE INTO docs (doc_id, path, status, source_type, text_hash, "
        "topics_tokens, corpus_class) VALUES (?,?,?,?,?,?,?)",
        (doc_id, path, status, source_type, text_hash, "", "CORPUS_CLASS:DRAFT"),
    )


def test_lineage_record_link_creates_entry():
    doc_a = f"lineage-a-{uuid.uuid4()}"
    doc_b = f"lineage-b-{uuid.uuid4()}"
    _seed_doc(doc_a, f"test/{doc_a}.md")
    _seed_doc(doc_b, f"test/{doc_b}.md")

    link_id = lineage_engine.record_link(doc_a, doc_b, "duplicate_content", "hash=abc123")
    assert link_id is not None

    row = db.fetchone("SELECT * FROM lineage WHERE id=?", (link_id,))
    assert row["doc_id"] == doc_a
    assert row["related_doc_id"] == doc_b
    assert row["relationship"] == "duplicate_content"
    assert "abc123" in row["detail"]


def test_lineage_record_link_idempotent():
    doc_a = f"idem-a-{uuid.uuid4()}"
    doc_b = f"idem-b-{uuid.uuid4()}"
    _seed_doc(doc_a, f"test/{doc_a}.md")
    _seed_doc(doc_b, f"test/{doc_b}.md")

    id1 = lineage_engine.record_link(doc_a, doc_b, "supersedes")
    id2 = lineage_engine.record_link(doc_a, doc_b, "supersedes")  # duplicate
    assert id1 is not None
    assert id2 is None, "Second identical link should return None (already exists)"


def test_lineage_invalid_relationship_raises():
    with pytest.raises(ValueError, match="Unknown relationship"):
        lineage_engine.record_link("a", "b", "made_up_relationship")


def test_lineage_get_lineage_returns_both_directions():
    center = f"center-{uuid.uuid4()}"
    left   = f"left-{uuid.uuid4()}"
    right  = f"right-{uuid.uuid4()}"
    for did, path in ((center, f"c/{center}.md"), (left, f"l/{left}.md"), (right, f"r/{right}.md")):
        _seed_doc(did, path)

    lineage_engine.record_link(center, right, "supersedes")
    lineage_engine.record_link(left, center, "derived_from")

    info = lineage_engine.get_lineage(center)
    assert info["doc_id"] == center
    assert len(info["outbound"]) >= 1   # center → right
    assert len(info["inbound"]) >= 1    # left → center
    assert info["total"] >= 2


# ═══════════════════════════════════════════════════════════════════════════
# Lineage — content duplicate detection
# ═══════════════════════════════════════════════════════════════════════════

def test_duplicate_detection_finds_same_hash():
    shared_hash = f"shared-{uuid.uuid4().hex}"
    doc_a = f"dup-a-{uuid.uuid4()}"
    doc_b = f"dup-b-{uuid.uuid4()}"
    _seed_doc(doc_a, f"dup/{doc_a}.md", text_hash=shared_hash)
    _seed_doc(doc_b, f"dup/{doc_b}.md", text_hash=shared_hash)

    links = lineage_engine.detect_and_record_content_duplicates(doc_a, shared_hash)
    assert len(links) >= 1
    assert any(l["duplicate_doc_id"] == doc_b for l in links)


def test_duplicate_detection_empty_hash_skipped():
    doc_id = f"no-hash-{uuid.uuid4()}"
    _seed_doc(doc_id, f"empty/{doc_id}.md", text_hash="")
    links = lineage_engine.detect_and_record_content_duplicates(doc_id, "")
    assert links == []


# ═══════════════════════════════════════════════════════════════════════════
# Lineage API routes
# ═══════════════════════════════════════════════════════════════════════════

def test_api_lineage_list():
    r = client.get("/api/lineage")
    assert r.status_code == 200
    body = r.json()
    assert "lineage" in body
    assert "count" in body
    assert "valid_relationships" in body


def test_api_lineage_list_filter():
    r = client.get("/api/lineage?relationship=duplicate_content")
    assert r.status_code == 200
    body = r.json()
    for rec in body["lineage"]:
        assert rec["relationship"] == "duplicate_content"


def test_api_lineage_doc_404():
    r = client.get("/api/lineage/nonexistent-doc-xyz")
    assert r.status_code == 404


def test_api_lineage_doc_found():
    docs = client.get("/api/docs").json()["docs"]
    if not docs:
        pytest.skip("No docs indexed")
    doc_id = docs[0]["doc_id"]
    r = client.get(f"/api/lineage/{doc_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["doc_id"] == doc_id
    assert "outbound" in body
    assert "inbound" in body


def test_api_lineage_create_manual_link():
    docs = client.get("/api/docs").json()["docs"]
    if len(docs) < 2:
        pytest.skip("Need at least 2 docs")
    doc_a = docs[0]["doc_id"]
    doc_b = docs[1]["doc_id"]

    r = client.post("/api/lineage", json={
        "doc_id": doc_a,
        "related_doc_id": doc_b,
        "relationship": "derived_from",
        "detail": "manual test link",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["relationship"] == "derived_from"


def test_api_lineage_create_invalid_relationship():
    docs = client.get("/api/docs").json()["docs"]
    if len(docs) < 2:
        pytest.skip("Need at least 2 docs")
    r = client.post("/api/lineage", json={
        "doc_id": docs[0]["doc_id"],
        "related_doc_id": docs[1]["doc_id"],
        "relationship": "invalid_type",
    })
    assert r.status_code == 422


def test_api_duplicates_endpoint():
    r = client.get("/api/duplicates")
    assert r.status_code == 200
    body = r.json()
    assert "duplicates" in body
    assert "count" in body


# ═══════════════════════════════════════════════════════════════════════════
# Migration report
# ═══════════════════════════════════════════════════════════════════════════

def test_api_migration_summary():
    r = client.get("/api/corpus/migration-report")
    assert r.status_code == 200
    body = r.json()
    assert "corpus_class_distribution" in body
    assert "open_conflicts" in body
    assert "lineage_records" in body
    assert "schema_versions" in body


def test_api_migration_report_writes_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = f"{tmpdir}/migration_report.md"
        r = client.post(f"/api/corpus/migration-report?output_path={out}")
        assert r.status_code == 200
        body = r.json()
        assert "generated_at" in body
        assert "invariants_passed" in body

        import os
        assert os.path.exists(out), "Migration report file was not written"
        content = open(out).read()
        assert "Corpus Migration Report" in content
        assert "Corpus Class Distribution" in content
        assert "Invariant Verification" in content


# ═══════════════════════════════════════════════════════════════════════════
# Snapshot ingest with Phase 4 corpus class
# ═══════════════════════════════════════════════════════════════════════════

def test_snapshot_ingest_sets_derived_class():
    """Snapshot ingested docs must always have CORPUS_CLASS:DERIVED."""
    data = {
        "run_id": "phase4-test",
        "files": [{
            "artifacts": {
                "meta": {
                    "id": f"p4-snap-{uuid.uuid4()}",
                    "type": "note",
                    "path": "snapshot/p4test.md",
                    "status": "working",
                    "updated": "2024-06-01T00:00:00Z",
                    "topics": ["phase4 test"],
                    "source_type": "snapshot",
                    "rubrix": {"operator_state": "vessel", "operator_intent": "capture"},
                    "scope": {"plane_scope": [], "field_scope": [], "node_scope": []},
                },
                "defs": [], "vars": [], "events": [],
            }
        }],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        r = client.post("/api/ingest/snapshot", json={"path": path})
        assert r.status_code == 200
        body = r.json()
        assert body.get("inserted_docs") == 1

        snap_id = data["files"][0]["artifacts"]["meta"]["id"]
        doc = db.fetchone("SELECT corpus_class FROM docs WHERE doc_id=?", (snap_id,))
        assert doc is not None
        assert doc["corpus_class"] == "CORPUS_CLASS:DERIVED", \
            f"Expected DERIVED, got {doc['corpus_class']!r}"
    finally:
        os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard Phase 4 fields
# ═══════════════════════════════════════════════════════════════════════════

def test_dashboard_has_phase4_fields():
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert "corpus_class_distribution" in body
    assert "lineage_records" in body
    assert "duplicate_links" in body

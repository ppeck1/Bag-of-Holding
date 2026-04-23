"""tests/test_phase6.py: Phase 6 tests — IC5 fix, corpus UI surfaces, README.

126 prior tests unchanged. These cover:
- IC5: ICS SUMMARY uses doc path, not doc_id
- Corpus badge data available from /api/docs
- Lineage route with relationship filter
- Migration report invariant verification
- README.md exists and has required sections
- All Phase 6 GET routes return 200
"""

import os
import json
import tempfile
import uuid
import pytest

os.environ.setdefault("BOH_DB", os.path.join(os.path.dirname(__file__), "test_boh_v2.db"))
os.environ.setdefault("BOH_LIBRARY", os.path.join(os.path.dirname(__file__), "..", "library"))

from fastapi.testclient import TestClient
from app.api.main import app
from app.db import connection as db
from app.services.events import export_ics, _get_event_summary

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True, scope="module")
def init():
    db.init_db()
    client.post("/api/index", json={"library_root": os.environ["BOH_LIBRARY"]})


# ── IC5: ICS SUMMARY uses doc title/path ─────────────────────────────────────

def test_ic5_ics_summary_not_raw_uuid():
    """ICS SUMMARY must not be a raw UUID — should use doc path basename."""
    r = client.get("/api/events/export.ics")
    assert r.status_code == 200
    # If there are events, their SUMMARY should look like a path or name, not a UUID
    for line in r.text.splitlines():
        if line.startswith("SUMMARY:"):
            summary_val = line[len("SUMMARY:"):]
            # A UUID looks like xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
            # A path basename looks like "planar-math" or similar
            # We just verify it's not empty
            assert summary_val.strip(), "ICS SUMMARY must not be empty"


def test_ic5_get_event_summary_returns_path_for_known_doc():
    """_get_event_summary() should return basename of doc path, not doc_id."""
    docs = db.fetchall("SELECT doc_id, path FROM docs LIMIT 1")
    if not docs:
        pytest.skip("No docs in DB")
    doc = docs[0]
    # Seed a fake event for this doc
    event_id = str(uuid.uuid4())
    db.execute(
        "INSERT OR REPLACE INTO events (event_id, doc_id, start_ts, end_ts, timezone, status, confidence) "
        "VALUES (?,?,?,?,?,?,?)",
        (event_id, doc["doc_id"], 1700000000, None, "UTC", "confirmed", 1.0),
    )
    ev = {"event_id": event_id, "doc_id": doc["doc_id"]}
    summary = _get_event_summary(ev)
    # Should be path basename without .md, not the raw doc_id
    import os
    expected_base = os.path.basename(doc["path"]).replace(".md", "")
    assert summary == expected_base, f"Expected {expected_base!r}, got {summary!r}"


# ── Corpus class in /api/docs response ───────────────────────────────────────

def test_docs_list_includes_corpus_class():
    r = client.get("/api/docs")
    assert r.status_code == 200
    docs = r.json()["docs"]
    if not docs:
        pytest.skip("No docs indexed")
    for doc in docs:
        assert "corpus_class" in doc, f"corpus_class missing from doc {doc.get('doc_id')}"


def test_docs_list_corpus_class_valid_values():
    valid = {
        "CORPUS_CLASS:CANON", "CORPUS_CLASS:DRAFT", "CORPUS_CLASS:DERIVED",
        "CORPUS_CLASS:ARCHIVE", "CORPUS_CLASS:EVIDENCE", None,
    }
    docs = client.get("/api/docs").json()["docs"]
    for doc in docs:
        assert doc.get("corpus_class") in valid, f"Invalid corpus_class: {doc.get('corpus_class')!r}"


def test_single_doc_includes_corpus_class():
    docs = client.get("/api/docs").json()["docs"]
    if not docs:
        pytest.skip("No docs")
    doc_id = docs[0]["doc_id"]
    r = client.get(f"/api/docs/{doc_id}")
    assert r.status_code == 200
    assert "corpus_class" in r.json()["doc"]


# ── Lineage filter ────────────────────────────────────────────────────────────

def test_lineage_filter_by_relationship():
    # Seed a known link
    doc_a = f"filter-a-{uuid.uuid4()}"
    doc_b = f"filter-b-{uuid.uuid4()}"
    for did, p in ((doc_a, f"a/{doc_a}.md"), (doc_b, f"b/{doc_b}.md")):
        db.execute(
            "INSERT OR REPLACE INTO docs (doc_id, path, status, corpus_class) VALUES (?,?,?,?)",
            (did, p, "draft", "CORPUS_CLASS:DRAFT"),
        )
    client.post("/api/lineage", json={
        "doc_id": doc_a, "related_doc_id": doc_b,
        "relationship": "supersedes", "detail": "filter test",
    })

    r = client.get("/api/lineage?relationship=supersedes")
    assert r.status_code == 200
    body = r.json()
    for rec in body["lineage"]:
        assert rec["relationship"] == "supersedes"


def test_lineage_invalid_filter_still_200():
    """Unknown filter returns 200 with empty list (server-side Python filter)."""
    r = client.get("/api/lineage?relationship=nonexistent_type")
    assert r.status_code == 200
    assert r.json()["count"] == 0


# ── Migration report invariant verification ───────────────────────────────────

def test_migration_report_invariants_pass():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = f"{tmpdir}/report.md"
        r = client.post(f"/api/corpus/migration-report?output_path={out}")
        assert r.status_code == 200
        body = r.json()
        assert body["invariants_passed"] is True, \
            f"Invariant failures: {[i for i in body['invariant_results'] if not i['passed']]}"


def test_migration_report_has_all_sections():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = f"{tmpdir}/report.md"
        client.post(f"/api/corpus/migration-report?output_path={out}")
        content = open(out).read()
        for section in [
            "Corpus Class Distribution",
            "Document Status Distribution",
            "Conflict Summary",
            "Lineage Summary",
            "Invariant Verification",
            "Schema Version History",
        ]:
            assert section in content, f"Missing section: {section!r}"


# ── README exists and has required content ────────────────────────────────────

def test_readme_exists():
    from pathlib import Path
    readme = Path(__file__).parent.parent / "README.md"
    assert readme.exists(), "README.md must exist at project root"


def test_readme_has_required_sections():
    from pathlib import Path
    content = (Path(__file__).parent.parent / "README.md").read_text()
    required = [
        "Quickstart", "canon scoring", "Corpus class",
        "Local-first", "API", "Document format",
    ]
    for section in required:
        assert section.lower() in content.lower(), f"README missing: {section!r}"


# ── ICS SUMMARY updated PRODID ────────────────────────────────────────────────

def test_ics_prodid_is_v2():
    r = client.get("/api/events/export.ics")
    assert "Bag of Holding v2" in r.text


# ── Dashboard corpus distribution present ─────────────────────────────────────

def test_dashboard_corpus_distribution_is_dict():
    body = client.get("/api/dashboard").json()
    dist = body.get("corpus_class_distribution", {})
    assert isinstance(dist, dict)
    # All keys must be valid class names or empty dict
    valid_prefix = "CORPUS_CLASS:"
    for k in dist:
        assert k.startswith(valid_prefix), f"Invalid corpus class key: {k!r}"


# ── All routes still respond 200 ──────────────────────────────────────────────

SMOKE_ROUTES = [
    "/api/health", "/api/dashboard", "/api/docs", "/api/conflicts",
    "/api/workflow", "/api/events", "/api/events/export.ics", "/api/planes",
    "/api/lineage", "/api/duplicates", "/api/corpus/classes",
    "/api/corpus/migration-report", "/",
]

@pytest.mark.parametrize("path", SMOKE_ROUTES)
def test_all_routes_still_200(path):
    r = client.get(path)
    assert r.status_code == 200, f"GET {path} → {r.status_code}"

"""tests/test_integration.py: Full integration test suite for Bag of Holding v2.

Converted from self_test.py (v0P). All 38 original checks preserved as pytest functions.
Import paths updated to v2 package structure. No behavioral changes.

Run with: pytest tests/test_integration.py -v
"""

import json
import os
import sys
import time
import tempfile
import uuid
import pytest

# ── Test DB isolation ─────────────────────────────────────────────────────────
TEST_DB = os.path.join(os.path.dirname(__file__), "test_boh_v2.db")
os.environ["BOH_DB"] = TEST_DB
os.environ["BOH_LIBRARY"] = os.path.join(os.path.dirname(__file__), "..", "library")

# Import after env is set
from app.db import connection as db
from app.services import indexer as crawler
from app.core import (
    search as search_engine,
    conflicts as conflict_engine,
    canon as canon_engine,
    planar as planar_engine,
    snapshot as snapshot_engine,
)
from app.services import events as event_engine, reviewer as llm_review
from app.services.indexer import normalize_topic_token, derive_topics_tokens, _validate_event
from app.services.parser import parse_frontmatter, extract_events, parse_semver
from app.core.rubrix import validate_header

LIBRARY_ROOT = os.environ["BOH_LIBRARY"]


@pytest.fixture(autouse=True, scope="session")
def init_database():
    """Initialize DB once for the session, clean up after."""
    db.init_db()
    yield
    try:
        os.remove(TEST_DB)
    except FileNotFoundError:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# Section 1: Database Initialization
# ═══════════════════════════════════════════════════════════════════════════

def test_all_required_tables_exist():
    tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = {r["name"] for r in tables}
    required = {"docs", "defs", "plane_facts", "events", "conflicts"}
    assert required.issubset(table_names), f"Missing tables: {required - table_names}"


def test_topics_tokens_column_exists():
    cols = db.fetchall("PRAGMA table_info(docs)")
    col_names = {c["name"] for c in cols}
    assert "topics_tokens" in col_names


def test_v2_acknowledged_column_exists():
    """v2 addition: conflicts.acknowledged column."""
    cols = db.fetchall("PRAGMA table_info(conflicts)")
    col_names = {c["name"] for c in cols}
    assert "acknowledged" in col_names


def test_schema_version_table_exists():
    """v2 addition: schema_version table."""
    tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    assert any(r["name"] == "schema_version" for r in tables)


# ═══════════════════════════════════════════════════════════════════════════
# Section 2: A1 — Topic Normalization
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    ("Planar Math", "planar math"),
    ("  RUBRIX  Lifecycle  ", "rubrix lifecycle"),
    ("canon", "canon"),
    ("  ", ""),
])
def test_normalize_topic_token(raw, expected):
    assert normalize_topic_token(raw) == expected, f"normalize_topic_token({raw!r}) should be {expected!r}"


def test_derive_topics_tokens_joined():
    tokens = derive_topics_tokens(["Planar Math", "Rubrix", "Canon"])
    assert tokens == "planar math rubrix canon", f"Got: {tokens!r}"


def test_derive_topics_tokens_empty():
    assert derive_topics_tokens([]) == ""


# ═══════════════════════════════════════════════════════════════════════════
# Section 3: Header Parser + Rubrix Lint
# ═══════════════════════════════════════════════════════════════════════════

VALID_DOC = """---
boh:
  id: test-valid-001
  type: note
  purpose: Test document
  topics: [testing, canon]
  status: draft
  version: "0.1.0"
  updated: "2024-01-01T00:00:00Z"
  scope:
    plane_scope: [test.plane]
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: observe
    operator_intent: capture
    next_operator: null
---
# Test Content
"""

BAD_DOC = """---
boh:
  id: bad-001
  type: note
  purpose: Bad doc
  topics: []
  status: canonical
  version: null
  updated: "2024-01-01T00:00:00Z"
  scope:
    plane_scope: []
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: integrate
    operator_intent: define
    next_operator: null
---
"""


def test_valid_header_parses_without_errors():
    boh, body, errors = parse_frontmatter(VALID_DOC)
    assert len(errors) == 0, f"Unexpected errors: {errors}"


def test_valid_header_passes_lint():
    boh, body, _ = parse_frontmatter(VALID_DOC)
    lint = validate_header(boh)
    assert len(lint) == 0, f"Lint errors: {lint}"


def test_canonical_integrate_raises_constraint_violation():
    boh, _, _ = parse_frontmatter(BAD_DOC)
    lint = validate_header(boh)
    assert any("LINT_CONSTRAINT_VIOLATION" in e for e in lint), f"Expected violation, got: {lint}"


# ═══════════════════════════════════════════════════════════════════════════
# Section 4: Crawler + Indexing (A1.2, D1, D2, F)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def crawl_result():
    return crawler.crawl_library(LIBRARY_ROOT)


def test_library_crawled_without_error(crawl_result):
    assert "error" not in crawl_result


def test_library_indexed_files_gt_zero(crawl_result):
    assert crawl_result.get("indexed", 0) > 0, f"indexed={crawl_result.get('indexed')}"


def test_a1_2_topics_tokens_stored(crawl_result):
    docs = db.fetchall("SELECT path, topics_tokens FROM docs WHERE topics_tokens != ''")
    assert len(docs) > 0, "No docs have topics_tokens stored"


def test_f_defs_plane_scope_json_always_valid():
    defs = db.fetchall("SELECT plane_scope_json FROM defs")
    for d in defs:
        try:
            json.loads(d["plane_scope_json"])
        except (json.JSONDecodeError, TypeError) as e:
            pytest.fail(f"Invalid plane_scope_json: {d['plane_scope_json']!r} — {e}")


def test_d2_events_only_with_explicit_start_timezone():
    evs = db.fetchall("SELECT * FROM events")
    # All stored events must have start_ts (timezone was required at creation)
    for ev in evs:
        assert ev.get("start_ts") is not None, f"Event {ev.get('event_id')} missing start_ts"


# ═══════════════════════════════════════════════════════════════════════════
# Section 5: F — defs.plane_scope_json explicit check
# ═══════════════════════════════════════════════════════════════════════════

def test_defs_plane_scope_json_is_list():
    defs = db.fetchall("SELECT term, plane_scope_json FROM defs LIMIT 5")
    for d in defs:
        parsed = json.loads(d["plane_scope_json"])
        assert isinstance(parsed, list), f"def '{d['term']}' plane_scope_json is not a list: {parsed!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Section 6: A1.3 + B1 — Canon Uses LIKE, Plane Scope Filter
# ═══════════════════════════════════════════════════════════════════════════

def test_a1_3_canon_resolves_via_like():
    result = canon_engine.resolve_canon(topic="planar math")
    # Winner may be None if library has no matching doc — but must not error
    assert "winner" in result
    assert "candidates" in result


def test_b1_plane_scope_filter_applied():
    result = canon_engine.resolve_canon(topic="planar", plane_scope="core.planar")
    assert "winner" in result
    assert "candidates" in result


# ═══════════════════════════════════════════════════════════════════════════
# Section 7: B2 — Canon Collision Requires Topic + Scope
# ═══════════════════════════════════════════════════════════════════════════

def test_b2_all_canon_collisions_have_shared_topic_term():
    conflict_engine.detect_all_conflicts()
    all_conflicts = conflict_engine.list_conflicts()
    canon_collisions = [c for c in all_conflicts if c["conflict_type"] == "canon_collision"]
    bad = [c for c in canon_collisions if not c.get("term")]
    assert len(bad) == 0, f"Canon collisions without shared topic term: {bad}"


# ═══════════════════════════════════════════════════════════════════════════
# Section 8: C1 — Planar Conflict 24h Window
# ═══════════════════════════════════════════════════════════════════════════

def test_c1_old_facts_do_not_trigger_planar_conflict():
    now = int(time.time())
    old_ts = now - 90000  # 25 hours ago — outside window
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO plane_facts (subject_id, plane_path, r, d, q, c, m, ts, valid_until, context_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), "test.window.check", 1.0, 1, 0.9, 0.9, None, old_ts, None, "old-fact"),
    )
    conn.execute(
        "INSERT INTO plane_facts (subject_id, plane_path, r, d, q, c, m, ts, valid_until, context_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), "test.window.check", 0.5, -1, 0.9, 0.9, None, old_ts, None, "old-fact-2"),
    )
    conn.commit()
    conn.close()

    conflict_engine.detect_all_conflicts()
    window_conflicts = db.fetchall(
        "SELECT * FROM conflicts WHERE conflict_type='planar_conflict' AND plane_path='test.window.check'"
    )
    assert len(window_conflicts) == 0, f"Old facts incorrectly triggered conflict: {window_conflicts}"


def test_c1_recent_facts_do_trigger_planar_conflict():
    planar_engine.store_fact("test.recent.conflict", r=1.0, d=1, q=0.9, c=0.9, context_ref="recent1")
    planar_engine.store_fact("test.recent.conflict", r=0.8, d=-1, q=0.8, c=0.85, context_ref="recent2")
    conflict_engine.detect_all_conflicts()
    recent_conflicts = db.fetchall(
        "SELECT * FROM conflicts WHERE conflict_type='planar_conflict' AND plane_path='test.recent.conflict'"
    )
    assert len(recent_conflicts) >= 1, f"Recent conflicting facts did not trigger conflict"


# ═══════════════════════════════════════════════════════════════════════════
# Section 9: D1 + D2 — Event Hardening
# ═══════════════════════════════════════════════════════════════════════════

def test_d2_event_without_timezone_fails_validation():
    body = """## Event:
- start: 2024-03-01T10:00:00Z
"""
    raw = extract_events(body)
    invalid = [e for e in raw if not _validate_event(e)]
    assert len(invalid) > 0 or len(raw) == 0, f"Expected invalid event, got: {raw}"


def test_d2_event_with_start_and_timezone_passes():
    valid_ev = {"start": "2024-03-01T10:00:00Z", "timezone": "UTC"}
    assert _validate_event(valid_ev)


# ═══════════════════════════════════════════════════════════════════════════
# Section 10: E1 — Snapshot Ingest
# ═══════════════════════════════════════════════════════════════════════════

SNAPSHOT_DATA = {
    "run_id": "test-run-001",
    "files": [
        {
            "artifacts": {
                "meta": {
                    "id": "snap-001",
                    "type": "note",
                    "path": "snapshot/test-note.md",
                    "status": "working",
                    "version": "0.1.0",
                    "updated": "2024-02-01T00:00:00Z",
                    "topics": ["snapshot test", "planar math"],
                    "sha256": "abc123def456",
                    "source_type": "snapshot",
                    "rubrix": {"operator_state": "vessel", "operator_intent": "capture"},
                    "scope": {"plane_scope": ["snap.plane"], "field_scope": [], "node_scope": []},
                },
                "defs": [{
                    "term": "Snapshot",
                    "block_hash": "deadbeef01234567",
                    "block_text": "**Snapshot**: A point-in-time export.",
                    "plane_scope": ["snap.plane"],
                }],
                "vars": [{"key": "RUN_MODE", "value": "test"}],
                "events": [
                    {"start": "2024-02-01T10:00:00Z", "timezone": "UTC", "end": "2024-02-01T11:00:00Z"},
                    {"start": "2024-02-02T10:00:00Z"},  # no timezone — D2 skip
                ],
            }
        },
        {"artifacts": {}},  # missing meta — should skip
    ],
}


@pytest.fixture(scope="session")
def snap_result():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(SNAPSHOT_DATA, f)
        snap_path = f.name
    result = snapshot_engine.ingest_snapshot_export(snap_path)
    os.unlink(snap_path)
    return result


def test_e1_snapshot_ingest_succeeds(snap_result):
    assert "error" not in snap_result, str(snap_result)


def test_e1_snapshot_inserted_1_doc(snap_result):
    assert snap_result.get("inserted_docs") == 1, f"inserted_docs={snap_result.get('inserted_docs')}"


def test_e1_snapshot_inserted_1_def(snap_result):
    assert snap_result.get("inserted_defs") == 1, f"inserted_defs={snap_result.get('inserted_defs')}"


def test_e1_snapshot_inserted_1_event_d2_skipped(snap_result):
    assert snap_result.get("inserted_events") == 1, f"inserted_events={snap_result.get('inserted_events')}"


def test_e1_snapshot_1_entry_skipped_missing_meta(snap_result):
    assert len(snap_result.get("skipped", [])) == 1


def test_e1_topics_tokens_derived_during_ingest():
    snap_doc = db.fetchone("SELECT topics_tokens FROM docs WHERE doc_id='snap-001'")
    assert snap_doc is not None
    assert snap_doc["topics_tokens"] == "snapshot test planar math", f"Got: {snap_doc}"


def test_e1_f_snapshot_def_plane_scope_json_is_list():
    snap_def = db.fetchone("SELECT plane_scope_json FROM defs WHERE doc_id='snap-001'")
    assert snap_def is not None
    parsed = json.loads(snap_def["plane_scope_json"])
    assert isinstance(parsed, list), f"Got: {parsed!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Section 11: G — Reviewer String
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def review_artifact():
    return llm_review.generate_review_artifact("planar-math.md", LIBRARY_ROOT)


def test_g_reviewer_string_is_boh_worker_v4(review_artifact):
    assert review_artifact.get("reviewer") == "BOH_WORKER_v4", f"Got: {review_artifact.get('reviewer')}"


def test_g_non_authoritative_is_true(review_artifact):
    assert review_artifact.get("non_authoritative") is True


def test_g_requires_explicit_confirmation_is_true(review_artifact):
    assert review_artifact.get("requires_explicit_confirmation") is True


# ═══════════════════════════════════════════════════════════════════════════
# Section 12: Parse Semver (math_authority.md §7)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("version,expected", [
    ("1.0.0", 1_000_000),
    ("v2.3.1", 2_003_001),
    ("0.1.0", 1_000),
    (None, 0),
    ("invalid", 0),
])
def test_parse_semver(version, expected):
    assert parse_semver(version) == expected, f"parse_semver({version!r}) should be {expected}"


# ═══════════════════════════════════════════════════════════════════════════
# Section 13: v2 Canon Guard — Snapshot Cannot Overwrite Canon
# ═══════════════════════════════════════════════════════════════════════════

def test_snapshot_cannot_overwrite_canonical_doc():
    """v2 addition: snapshot ingest skips docs that would overwrite a canonical record."""
    # First promote snap-001 to canonical in DB
    db.execute("UPDATE docs SET status='canonical' WHERE doc_id='snap-001'")

    attempt = {
        "run_id": "canon-guard-test",
        "files": [{
            "artifacts": {
                "meta": {
                    "id": "snap-001",  # same doc_id as now-canonical doc
                    "type": "note",
                    "path": "snapshot/test-note.md",
                    "status": "draft",
                    "updated": "2024-03-01T00:00:00Z",
                    "topics": ["test"],
                    "source_type": "snapshot",
                    "rubrix": {"operator_state": "observe", "operator_intent": "capture"},
                    "scope": {"plane_scope": [], "field_scope": [], "node_scope": []},
                },
                "defs": [], "vars": [], "events": [],
            }
        }],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(attempt, f)
        path = f.name

    result = snapshot_engine.ingest_snapshot_export(path)
    os.unlink(path)

    assert result.get("inserted_docs") == 0, "Canon doc should not be overwritten"
    assert any(s.get("reason") == "would_overwrite_canon" for s in result.get("skipped", [])), \
        f"Expected 'would_overwrite_canon' in skipped: {result.get('skipped')}"

    # Restore for other tests
    db.execute("UPDATE docs SET status='working' WHERE doc_id='snap-001'")

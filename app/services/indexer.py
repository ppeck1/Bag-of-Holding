"""app/services/indexer.py: Filesystem crawler and document indexer for Bag of Holding v2.

Moved from crawler.py (v0P). Core logic unchanged.
Phase 4 additions:
  - corpus_class assigned after every index_file() call (Step 4.2)
  - content duplicate detection + lineage linking (Step 4.3)
  - supersession detection (Step 4.3)
Phase 8 additions (Daenary + DCNS):
  - parse_frontmatter_full() used to capture optional daenary: block
  - Daenary coordinates persisted to doc_coordinates after doc insert
  - DCNS edge sync called after indexing completes

All v0P behaviors (A1.1–A1.3, D1, D2, F, I1–I13) preserved exactly.
"""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from app.db import connection as db
from app.services.parser import (
    parse_frontmatter_full,
    extract_definitions,
    extract_events,
    parse_iso_to_epoch,
)
from app.core.rubrix import validate_header
from app.core.corpus import classify
from app.core.lineage import detect_and_record_content_duplicates, detect_supersession
from app.core.daenary import extract_coordinates, upsert_coordinates, validate_daenary_block


# ── A1.1: Deterministic topic normalization ───────────────────────────────────

def normalize_topic_token(topic: str) -> str:
    """Lowercase, trim, collapse internal whitespace. Deterministic. No mutation."""
    return " ".join(topic.strip().lower().split())


def derive_topics_tokens(topics_array: list) -> str:
    """A1.2: Derive topics_tokens string from topics array. Always deterministic."""
    if not topics_array:
        return ""
    return " ".join(normalize_topic_token(t) for t in topics_array if t)


# ── Helpers ───────────────────────────────────────────────────────────────────

def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def extract_title(boh: dict, body: str) -> str:
    if "purpose" in boh:
        return boh["purpose"][:120]
    for line in body.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()[:120]
    return ""


def infer_source_type(path: Path) -> str:
    if "/canon/" in str(path):
        return "canon_folder"
    return "library"


# ── D2: Validate event has explicit start + timezone ─────────────────────────

def _validate_event(ev: dict) -> bool:
    """Return True only if event has explicit start (ISO8601) and timezone."""
    start = ev.get("start")
    tz = ev.get("timezone")
    if not start or not tz:
        return False
    return parse_iso_to_epoch(start) is not None


# ── Main indexer ──────────────────────────────────────────────────────────────

def index_file(path: Path, library_root: Path) -> dict:
    """Index a single markdown file. Returns result dict with lint_errors.

    Phase 4 additions on top of preserved v0P logic:
      - corpus_class assigned after DB write
      - content duplicate detection + lineage recording
      - supersession detection + lineage recording
    Phase 8 additions:
      - parse_frontmatter_full() captures optional daenary: block
      - Daenary coordinates persisted to doc_coordinates
      - Daenary lint warnings added (non-destructive)
    """
    rel_path = str(path.relative_to(library_root))
    text = path.read_text(encoding="utf-8", errors="replace")

    # Phase 8: use full parser to capture daenary: block
    boh, raw_header, body, parse_errors = parse_frontmatter_full(text)

    if boh is None:
        return {
            "path": rel_path,
            "doc_id": None,
            "lint_errors": parse_errors,
            "indexed": False,
        }

    lint_errors = parse_errors + validate_header(boh)
    doc_id = boh.get("id") or str(uuid.uuid4())
    scope = boh.get("scope", {}) or {}
    rubrix = boh.get("rubrix", {}) or {}

    plane_scope = scope.get("plane_scope") or []
    field_scope = scope.get("field_scope") or []
    node_scope  = scope.get("node_scope") or []

    updated_ts  = parse_iso_to_epoch(boh.get("updated")) or int(time.time())
    source_type = infer_source_type(path)
    title       = extract_title(boh, body)
    topics      = boh.get("topics") or []
    text_hash   = hash_text(text)

    # A1.2: Derive topics_tokens deterministically — never trust cached value
    topics_tokens = derive_topics_tokens(topics)

    # Build doc dict for classification
    doc_dict = {
        "status": boh.get("status"),
        "operator_state": rubrix.get("operator_state"),
        "source_type": source_type,
        "type": boh.get("type"),
        "topics_tokens": topics_tokens,
    }
    corpus_class = classify(doc_dict)

    # Phase 8: extract + validate Daenary coordinates (non-destructive)
    daenary_block = raw_header.get("daenary") if isinstance(raw_header, dict) else None
    daenary_coords, daenary_warnings = extract_coordinates(daenary_block)
    lint_errors = lint_errors + daenary_warnings

    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO docs
              (doc_id, path, type, status, version, updated_ts,
               operator_state, operator_intent,
               plane_scope_json, field_scope_json, node_scope_json,
               text_hash, source_type, topics_tokens, corpus_class)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                doc_id, rel_path,
                boh.get("type"), boh.get("status"),
                boh.get("version"), updated_ts,
                rubrix.get("operator_state"), rubrix.get("operator_intent"),
                json.dumps(plane_scope), json.dumps(field_scope), json.dumps(node_scope),
                text_hash, source_type, topics_tokens, corpus_class,
            ),
        )

        # FTS — delete old row by path then reinsert
        conn.execute("DELETE FROM docs_fts WHERE path = ?", (rel_path,))
        conn.execute(
            "INSERT INTO docs_fts(content, title, path, topics) VALUES (?,?,?,?)",
            (body, title, rel_path, json.dumps(topics)),
        )

        # F: Definitions — always use json.dumps for plane_scope_json
        conn.execute("DELETE FROM defs WHERE doc_id = ?", (doc_id,))
        defs = extract_definitions(body, plane_scope)
        for d in defs:
            conn.execute(
                "INSERT INTO defs (doc_id, term, block_hash, block_text, plane_scope_json) VALUES (?,?,?,?,?)",
                (doc_id, d["term"], d["block_hash"], d["block_text"], json.dumps(plane_scope)),
            )

        # D1 + D2: Events — explicit start + timezone required
        conn.execute("DELETE FROM events WHERE doc_id = ?", (doc_id,))
        raw_events = extract_events(body)
        potential_events_detected = []
        for ev in raw_events:
            if _validate_event(ev):
                event_id  = str(uuid.uuid4())
                start_ts  = parse_iso_to_epoch(ev["start"])
                end_ts    = parse_iso_to_epoch(ev.get("end"))
                conn.execute(
                    "INSERT INTO events (event_id, doc_id, start_ts, end_ts, timezone, status, confidence) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (event_id, doc_id, start_ts, end_ts, ev["timezone"], "confirmed", 1.0),
                )
            else:
                potential_events_detected.append(ev)

        # Phase 8: persist Daenary coordinates (replace old rows)
        upsert_coordinates(conn, doc_id, daenary_coords)

        conn.commit()
    finally:
        conn.close()

    # Phase 4: duplicate detection + lineage (after commit, using separate connections)
    duplicate_links = detect_and_record_content_duplicates(doc_id, text_hash)

    # Phase 4: supersession detection
    full_doc = {
        "status": boh.get("status"),
        "topics_tokens": topics_tokens,
        "plane_scope_json": json.dumps(plane_scope),
        "version": boh.get("version"),
    }
    supersession_links = detect_supersession(doc_id, full_doc)

    result = {
        "path": rel_path,
        "doc_id": doc_id,
        "lint_errors": lint_errors,
        "indexed": True,
        "title": title,
        "topics_tokens": topics_tokens,
        "corpus_class": corpus_class,
    }
    if daenary_coords:
        result["daenary_coordinates"] = len(daenary_coords)
    if potential_events_detected:
        result["potential_events_detected"] = potential_events_detected
    if duplicate_links:
        result["duplicate_links"] = duplicate_links
    if supersession_links:
        result["supersession_links"] = supersession_links

    return result


def crawl_library(library_root: str) -> dict:
    """Crawl all markdown files under library_root. Returns summary.

    Phase 4: returns lineage_events count in summary.
    Phase 8: returns daenary_coordinates count; syncs DCNS edges after crawl.
    """
    root = Path(library_root).resolve()
    if not root.exists():
        return {"error": f"Library root does not exist: {library_root}"}

    results = []
    for path in sorted(root.rglob("*.md")):
        if path.name.endswith(".review.md"):
            continue  # I2: skip review artifacts
        result = index_file(path, root)
        results.append(result)

    indexed      = [r for r in results if r.get("indexed")]
    errors       = [r for r in results if r.get("lint_errors")]
    dup_events   = sum(len(r.get("duplicate_links", [])) for r in results)
    super_events = sum(len(r.get("supersession_links", [])) for r in results)
    daenary_total = sum(r.get("daenary_coordinates", 0) for r in results)

    # Phase 8: sync DCNS edges from lineage + conflicts after full crawl
    dcns_summary = {}
    try:
        from app.core.dcns import sync_edges
        dcns_summary = sync_edges()
    except Exception:
        pass

    return {
        "total_files": len(results),
        "indexed": len(indexed),
        "files_with_lint_errors": len(errors),
        "lineage_events": dup_events + super_events,
        "duplicate_links_created": dup_events,
        "supersession_links_created": super_events,
        "daenary_coordinates_indexed": daenary_total,
        "dcns_edges_synced": dcns_summary.get("edges_written", 0),
        "results": results,
    }

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
from app.core.metadata_contract import extract_contract
from app.core.authority_state import assert_import_transition


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
    """Return the best available title for a document.
    Priority: boh.purpose → first markdown heading → empty string."""
    if "purpose" in boh:
        return boh["purpose"][:120]
    for line in body.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()[:120]
    return ""


def extract_summary(body: str, max_len: int = 220) -> str:
    """Derive a plain-text preview snippet from the document body.

    Takes the first non-heading, non-empty paragraph and strips markdown syntax.
    Result is trimmed to max_len characters. Deterministic — no LLM involved.
    """
    import re as _re
    # Split on blank lines to get paragraphs
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        # Skip headings and horizontal rules
        if block.startswith("#") or block.startswith("---") or block.startswith("==="):
            continue
        # Skip code blocks
        if block.startswith("```") or block.startswith("    "):
            continue
        # Strip common markdown: bold, italic, links, backticks
        clean = _re.sub(r"!\[.*?\]\(.*?\)", "", block)       # images
        clean = _re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)  # links
        clean = _re.sub(r"[*_`#>]", "", clean)               # emphasis, headings, blockquote
        clean = _re.sub(r"\s+", " ", clean).strip()
        if len(clean) >= 20:
            return clean[:max_len]
    return ""
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

def _preprocess_for_index(path: Path, text: str) -> str:
    """Convert non-Markdown files to indexable Markdown-like text.

    .html/.htm  → strip boilerplate (scripts, styles, nav), extract title,
                  headings as Markdown headers, body text normalized
    .json       → pretty-print as code block; graceful failure on invalid JSON
    .txt        → pass through as-is
    .md/.markdown → pass through unchanged

    Returns a string that parse_frontmatter_full() can safely process.
    Non-markdown files get a minimal injected boh: header so they index cleanly.
    """
    import re
    suffix = path.suffix.lower()

    if suffix in ('.html', '.htm'):
        # Phase 26.2: improved HTML normalization
        # 1. Remove script/style/nav/header/footer blocks WITH their content
        text_clean = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.I | re.S)
        text_clean = re.sub(r'<style[^>]*>.*?</style>', ' ', text_clean, flags=re.I | re.S)
        text_clean = re.sub(r'<nav[^>]*>.*?</nav>', ' ', text_clean, flags=re.I | re.S)
        text_clean = re.sub(r'<header[^>]*>.*?</header>', ' ', text_clean, flags=re.I | re.S)
        text_clean = re.sub(r'<footer[^>]*>.*?</footer>', ' ', text_clean, flags=re.I | re.S)
        text_clean = re.sub(r'<!--.*?-->', ' ', text_clean, flags=re.S)

        # 2. Extract <title>
        title_m = re.search(r'<title[^>]*>([^<]+)</title>', text_clean, re.I)
        title = title_m.group(1).strip() if title_m else ''

        # 3. Extract headings as Markdown
        heading_lines = []
        for m in re.finditer(r'<h([1-4])[^>]*>([^<]+)</h\1>', text_clean, re.I):
            level = int(m.group(1))
            heading_text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if heading_text:
                heading_lines.append('#' * level + ' ' + heading_text)
        if not title and heading_lines:
            title = re.sub(r'^#+\s*', '', heading_lines[0])

        # 4. Strip remaining tags, normalize whitespace
        body = re.sub(r'<[^>]+>', ' ', text_clean)
        body = re.sub(r'[ \t]+', ' ', body)
        body = '\n'.join(l.strip() for l in body.splitlines() if l.strip())

        # 5. Prepend extracted headings for topic extraction
        if heading_lines:
            body = '\n'.join(heading_lines) + '\n\n' + body

        # Truncate and build output
        body = body[:4000]
        title = title or path.stem.replace('-', ' ').replace('_', ' ').title()
        return (
            f"---\nboh:\n  id: html-{path.stem[:40]}\n  type: reference\n"
            f"  purpose: {title[:120]}\n  status: draft\n  version: \"0.1.0\"\n"
            f"  updated: \"2026-01-01T00:00:00Z\"\n  rubrix:\n"
            f"    operator_state: observe\n    operator_intent: capture\n---\n\n"
            f"# {title}\n\n{body}"
        )

    if suffix == '.json':
        import json as _json
        # Phase 26.2: graceful failure with clear error record (not silent corruption)
        try:
            data = _json.loads(text)
            is_valid = True
        except Exception as exc:
            data = {"_parse_error": str(exc), "_raw_preview": text[:200]}
            is_valid = False
        title = (data.get('title') or data.get('name') or data.get('id')
                 or path.stem.replace('-', ' ').replace('_', ' ').title())
        body = _json.dumps(data, indent=2)[:3000]
        validity_note = "" if is_valid else "\n> ⚠ JSON parse error — content may be malformed.\n"
        return (
            f"---\nboh:\n  id: json-{path.stem[:40]}\n  type: reference\n"
            f"  purpose: {str(title)[:120]}\n  status: draft\n  version: \"0.1.0\"\n"
            f"  updated: \"2026-01-01T00:00:00Z\"\n  rubrix:\n"
            f"    operator_state: observe\n    operator_intent: capture\n---\n\n"
            f"# {title}\n{validity_note}\n```json\n{body}\n```"
        )

    if suffix in ('.txt',):
        # Check if it already has boh: frontmatter
        if '---' in text[:200] and 'boh:' in text[:400]:
            return text
        title = path.stem.replace('-', ' ').replace('_', ' ').title()
        return (
            f"---\nboh:\n  id: txt-{path.stem[:40]}\n  type: note\n"
            f"  purpose: {title}\n  status: draft\n  version: \"0.1.0\"\n"
            f"  updated: \"2026-01-01T00:00:00Z\"\n  rubrix:\n"
            f"    operator_state: observe\n    operator_intent: capture\n---\n\n"
            f"# {title}\n\n{text[:4000]}"
        )

    return text  # .md, .markdown — pass through unchanged


def index_file(path: Path, library_root: Path) -> dict:
    """Index a single file (Markdown, HTML, JSON, or plain text).

    Phase 4 additions on top of preserved v0P logic:
      - corpus_class assigned after DB write
      - content duplicate detection + lineage recording
      - supersession detection + lineage recording
    Phase 8 additions:
      - parse_frontmatter_full() captures optional daenary: block
      - Daenary coordinates persisted to doc_coordinates
      - Daenary lint warnings added (non-destructive)
    Phase 13 additions:
      - Multi-format preprocessing: .html, .json, .txt converted to indexable MD
    """
    rel_path = path.relative_to(library_root).as_posix()
    raw_bytes = path.read_bytes()
    text = raw_bytes.decode("utf-8", errors="replace")

    # Phase 13: preprocess non-markdown files
    text = _preprocess_for_index(path, text)

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
    topics      = boh.get("topics") or []
    text_hash   = hash_text(text)

    # Phase 14: governed metadata contract. Missing metadata does not block
    # legacy readability; it moves the document into Quarantine / Legacy Import.
    contract, contract_errors = extract_contract(boh, rel_path, text_hash, allow_legacy=True)
    doc_id = doc_id
    lint_errors = lint_errors + [f"{e.get('code')}: {e.get('message')}" for e in contract_errors]

    # A1.2: Derive topics_tokens deterministically — never trust cached value
    topics_tokens = derive_topics_tokens(topics)
    title         = contract.get("title") or extract_title(boh, body)
    summary       = extract_summary(body)

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

    # Phase 14: Canonical authority lock — only block if the transition is
    # genuinely forbidden (e.g. raw->canonical without approval, or overwriting
    # an existing canonical document).
    # Non-authoritative intake (raw->draft, raw->scratch, etc.) must pass freely.
    try:
        assert_import_transition(doc_id, contract["status"], approved=False)
    except ValueError as exc:
        # Only hard-block if it's a canonical overwrite protection issue.
        # For ordinary intake failures, record as lint_error but still index.
        error_msg = str(exc)
        is_canon_overwrite = "cannot be overwritten" in error_msg or "Canonical promotion" in error_msg
        if is_canon_overwrite:
            return {
                "path": rel_path,
                "doc_id": doc_id,
                "lint_errors": lint_errors + contract_errors + [error_msg],
                "indexed": False,
                "authority_blocked": True,
            }
        # Non-fatal: record and continue
        lint_errors = lint_errors + [error_msg]

    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO docs
              (doc_id, path, type, status, version, updated_ts,
               operator_state, operator_intent,
               plane_scope_json, field_scope_json, node_scope_json,
               text_hash, source_type, topics_tokens, corpus_class,
               title, summary,
               project, document_class, canonical_layer, authority_state,
               review_state, provenance_json, source_hash, document_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                doc_id, rel_path,
                boh.get("type") or contract.get("document_class"), contract.get("status"),
                boh.get("version"), updated_ts,
                rubrix.get("operator_state"), rubrix.get("operator_intent"),
                json.dumps(plane_scope), json.dumps(field_scope), json.dumps(node_scope),
                text_hash, source_type, topics_tokens, corpus_class,
                title, summary,
                contract.get("project"), contract.get("document_class"),
                contract.get("canonical_layer"), contract.get("authority_state"),
                contract.get("review_state"), json.dumps(contract.get("provenance") or {}),
                contract.get("source_hash"), doc_id,
            ),
        )

        # Phase 15.6: first-class product state. Keep backend status intact;
        # app_state supports the humane Inbox → Review → Library workflow.
        app_state = "inbox" if contract.get("status") in ("draft", "working", None, "") else "library"
        try:
            conn.execute("UPDATE docs SET app_state = ? WHERE doc_id = ?", (app_state, doc_id))
        except Exception:
            pass

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

    # Phase 19: wrap indexed document as a PlaneCard
    try:
        from app.core.plane_card import wrap_and_persist
        full_indexed_doc = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
        if full_indexed_doc:
            wrap_and_persist(dict(full_indexed_doc))
    except Exception:
        pass  # PlaneCard wrapping is non-fatal; never blocks indexing

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
        "summary": summary,
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

    # Phase 13: scan multiple supported formats
    SUPPORTED_GLOBS = ["*.md", "*.html", "*.htm", "*.json", "*.txt", "*.markdown"]
    seen = set()
    all_paths = []
    for glob in SUPPORTED_GLOBS:
        for path in sorted(root.rglob(glob)):
            if str(path) in seen:
                continue
            seen.add(str(path))
            if path.name.endswith(".review.md") or path.name.endswith(".review.json"):
                continue  # I2: skip review artifacts
            all_paths.append(path)

    results = []
    for path in all_paths:
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

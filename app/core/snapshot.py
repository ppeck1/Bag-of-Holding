"""app/core/snapshot.py: Snapshot export ingest for Bag of Holding v2.

Phase 4 additions on top of v0P logic:
  - corpus_class assigned during ingest (always CORPUS_CLASS:DERIVED for snapshots)
  - content duplicate detection + lineage recording
  - canon guard already present from Phase 2
"""

import json
import uuid
from pathlib import Path

from app.db import connection as db
from app.services.indexer import derive_topics_tokens
from app.services.parser import parse_iso_to_epoch
from app.core.corpus import CLASS_DERIVED
from app.core.lineage import detect_and_record_content_duplicates


def ingest_snapshot_export(path_to_json: str) -> dict:
    """Load a worker snapshot export JSON and populate the DB.

    Expected structure: { run_id, files: [{ artifacts: { meta, defs, vars, events } }] }

    Preserved behaviors: SI1–SI7 (D2, F, A1.2, canon guard).
    Phase 4: corpus_class=DERIVED set on all snapshot docs, duplicate lineage recorded.
    """
    snapshot_path = Path(path_to_json)
    if not snapshot_path.exists():
        return {"error": f"Snapshot file not found: {path_to_json}"}

    try:
        export_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    run_id = export_data.get("run_id", "unknown")
    files  = export_data.get("files", [])

    inserted_docs   = 0
    inserted_defs   = 0
    inserted_events = 0
    duplicate_links = 0
    skipped         = []

    conn = db.get_conn()
    try:
        for file_entry in files:
            artifacts = file_entry.get("artifacts", {})
            meta = artifacts.get("meta")
            if not meta:
                skipped.append({"reason": "missing artifacts.meta", "entry": str(file_entry)[:80]})
                continue

            doc_id = meta.get("id") or str(uuid.uuid4())

            # Canon guard (corpus_migration_doctrine §3b)
            existing = conn.execute(
                "SELECT status FROM docs WHERE doc_id = ?", (doc_id,)
            ).fetchone()
            if existing and existing[0] == "canonical":
                skipped.append({"reason": "would_overwrite_canon", "doc_id": doc_id})
                continue

            path          = meta.get("path") or f"snapshot/{doc_id}.md"
            doc_type      = meta.get("type")
            status        = meta.get("status")
            version       = meta.get("version")
            updated_ts    = parse_iso_to_epoch(meta.get("updated"))
            operator_state  = meta.get("operator_state") or (meta.get("rubrix") or {}).get("operator_state")
            operator_intent = meta.get("operator_intent") or (meta.get("rubrix") or {}).get("operator_intent")

            scope       = meta.get("scope") or {}
            plane_scope = scope.get("plane_scope") or []
            field_scope = scope.get("field_scope") or []
            node_scope  = scope.get("node_scope") or []

            text_hash     = meta.get("sha256") or meta.get("text_hash") or ""
            topics        = meta.get("topics") or []
            topics_tokens = derive_topics_tokens(topics)  # A1.2: always re-derive
            source_type   = meta.get("source_type") or "snapshot"

            # Phase 4: snapshots are always DERIVED
            corpus_class = CLASS_DERIVED

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
                    doc_id, path, doc_type, status, version, updated_ts,
                    operator_state, operator_intent,
                    json.dumps(plane_scope), json.dumps(field_scope), json.dumps(node_scope),
                    text_hash, source_type, topics_tokens, corpus_class,
                ),
            )
            inserted_docs += 1

            # Defs — F: always json.dumps
            conn.execute("DELETE FROM defs WHERE doc_id = ?", (doc_id,))
            for def_entry in artifacts.get("defs") or []:
                term = def_entry.get("term")
                if not term:
                    continue
                ps = def_entry.get("plane_scope") or []
                conn.execute(
                    "INSERT INTO defs (doc_id, term, block_hash, block_text, plane_scope_json) VALUES (?,?,?,?,?)",
                    (doc_id, term, def_entry.get("block_hash") or "", def_entry.get("block_text") or "", json.dumps(ps)),
                )
                inserted_defs += 1

            # Events — D2: skip if no explicit start + timezone
            conn.execute("DELETE FROM events WHERE doc_id = ?", (doc_id,))
            for ev in artifacts.get("events") or []:
                start = ev.get("start")
                tz    = ev.get("timezone")
                if not start or not tz:
                    continue
                start_ts = parse_iso_to_epoch(start)
                if start_ts is None:
                    continue
                end_ts   = parse_iso_to_epoch(ev.get("end"))
                event_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO events (event_id, doc_id, start_ts, end_ts, timezone, status, confidence) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (event_id, doc_id, start_ts, end_ts, tz, "confirmed", 1.0),
                )
                inserted_events += 1

        conn.commit()
    finally:
        conn.close()

    # Phase 4: content duplicate detection (after commit)
    all_new = db.fetchall(
        "SELECT doc_id, text_hash FROM docs WHERE source_type='snapshot' AND text_hash != ''"
    )
    for row in all_new:
        links = detect_and_record_content_duplicates(row["doc_id"], row["text_hash"])
        duplicate_links += len(links)

    return {
        "run_id": run_id,
        "source": str(snapshot_path),
        "inserted_docs": inserted_docs,
        "inserted_defs": inserted_defs,
        "inserted_events": inserted_events,
        "duplicate_links_created": duplicate_links,
        "skipped": skipped,
    }

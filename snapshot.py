"""snapshot.py: Snapshot export ingest for Bag of Holding v0P.

Bucket E: Ingest boh_export_<run_id>.json from BOH_WORKER_v2.1.
Does NOT modify meta structure, recompute hashes, or infer fields.
"""

import json
import uuid
from pathlib import Path

import db
from crawler import derive_topics_tokens
from parser import parse_iso_to_epoch


def ingest_snapshot_export(path_to_json: str) -> dict:
    """
    Load a worker snapshot export JSON and populate the DB.

    Expected top-level structure:
      {
        "run_id": "...",
        "files": [
          {
            "artifacts": {
              "meta": { ...boh header fields... },
              "defs": [ {"term": ..., "block_hash": ..., "block_text": ..., "plane_scope": [...]} ],
              "vars": [ {"key": ..., "value": ...} ],
              "events": [ {"start": ..., "timezone": ..., "end": ...} ]
            }
          },
          ...
        ]
      }
    """
    snapshot_path = Path(path_to_json)
    if not snapshot_path.exists():
        return {"error": f"Snapshot file not found: {path_to_json}"}

    try:
        export_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    run_id = export_data.get("run_id", "unknown")
    files = export_data.get("files", [])

    inserted_docs = 0
    inserted_defs = 0
    inserted_events = 0
    skipped = []

    conn = db.get_conn()
    try:
        for file_entry in files:
            artifacts = file_entry.get("artifacts", {})
            meta = artifacts.get("meta")
            if not meta:
                skipped.append({"reason": "missing artifacts.meta", "entry": str(file_entry)[:80]})
                continue

            doc_id = meta.get("id") or str(uuid.uuid4())
            path = meta.get("path") or f"snapshot/{doc_id}.md"
            doc_type = meta.get("type")
            status = meta.get("status")
            version = meta.get("version")
            updated_ts = parse_iso_to_epoch(meta.get("updated"))
            operator_state = meta.get("operator_state") or (meta.get("rubrix") or {}).get("operator_state")
            operator_intent = meta.get("operator_intent") or (meta.get("rubrix") or {}).get("operator_intent")

            scope = meta.get("scope") or {}
            plane_scope = scope.get("plane_scope") or []
            field_scope = scope.get("field_scope") or []
            node_scope = scope.get("node_scope") or []

            # Use sha256 from meta if present; do NOT recompute
            text_hash = meta.get("sha256") or meta.get("text_hash") or ""

            topics = meta.get("topics") or []
            # A1.2: Derive topics_tokens during insertion
            topics_tokens = derive_topics_tokens(topics)

            source_type = meta.get("source_type") or "snapshot"

            conn.execute(
                """
                INSERT OR REPLACE INTO docs
                  (doc_id, path, type, status, version, updated_ts,
                   operator_state, operator_intent,
                   plane_scope_json, field_scope_json, node_scope_json,
                   text_hash, source_type, topics_tokens)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    doc_id, path, doc_type, status, version, updated_ts,
                    operator_state, operator_intent,
                    json.dumps(plane_scope), json.dumps(field_scope), json.dumps(node_scope),
                    text_hash, source_type, topics_tokens,
                ),
            )
            inserted_docs += 1

            # Defs
            conn.execute("DELETE FROM defs WHERE doc_id = ?", (doc_id,))
            for def_entry in artifacts.get("defs") or []:
                term = def_entry.get("term")
                if not term:
                    continue
                ps = def_entry.get("plane_scope") or []
                conn.execute(
                    "INSERT INTO defs (doc_id, term, block_hash, block_text, plane_scope_json) VALUES (?,?,?,?,?)",
                    (
                        doc_id,
                        term,
                        def_entry.get("block_hash") or "",
                        def_entry.get("block_text") or "",
                        json.dumps(ps),  # F: always json.dumps
                    ),
                )
                inserted_defs += 1

            # Events — D2: only if explicit start + timezone present
            conn.execute("DELETE FROM events WHERE doc_id = ?", (doc_id,))
            for ev in artifacts.get("events") or []:
                start = ev.get("start")
                tz = ev.get("timezone")
                if not start or not tz:
                    continue  # D2: no inference
                start_ts = parse_iso_to_epoch(start)
                if start_ts is None:
                    continue
                end_ts = parse_iso_to_epoch(ev.get("end"))
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

    return {
        "run_id": run_id,
        "source": str(snapshot_path),
        "inserted_docs": inserted_docs,
        "inserted_defs": inserted_defs,
        "inserted_events": inserted_events,
        "skipped": skipped,
    }

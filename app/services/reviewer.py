"""app/services/reviewer.py: LLM review artifact generation for Bag of Holding v2.

Moved from llm_review.py (v0P). Logic unchanged.
Phase 9 additions:
  - load_review_artifact() — load existing artifact without regenerating
  - review_artifact_exists() — check without loading
  - artifact now includes doc_title, doc_id, doc_status
  - suspected_conflicts enriched with titles + paths

Review artifacts are non-authoritative. They cannot overwrite canon automatically.
All patches require explicit user confirmation.

See docs/corpus_migration_doctrine.md §7 for artifact doctrine.
"""

import hashlib
import json
import re
import time
from pathlib import Path

from app.db import connection as db
from app.services.parser import parse_frontmatter, extract_definitions


def _v4_folder_from_status(status: str) -> str:
    if status == "canonical":
        return "01_sources\\canon\\"
    if status == "archived":
        return "01_sources\\archive\\"
    if status == "draft":
        return "01_sources\\drafts\\"
    if status == "working":
        return "01_sources\\working\\"
    return "01_sources\\unknown\\"


def _v4_placement_suggestion_from_meta(meta: dict) -> dict:
    """Deterministic placement suggestion. Uses meta.status/meta.type only. No inference."""
    status = (meta or {}).get("status")
    doc_type = (meta or {}).get("type")

    folder = _v4_folder_from_status(status or "")
    reasoning = []

    if status in {"canonical", "archived", "draft", "working"}:
        reasoning.append(f"meta.status={status} → {folder}")
    else:
        reasoning.append("meta.status missing/unknown → 01_sources\\unknown\\")

    if doc_type in {"event", "ledger", "person"} and status != "canonical":
        folder = "01_sources\\working\\"
        reasoning.append("type in {event,ledger,person} AND status!=canonical → 01_sources\\working\\")

    return {"recommended_folder": folder, "reasoning": reasoning}


def _resolve_doc_path(doc_path: str, library_root: str) -> tuple[str, Path] | tuple[None, None]:
    """Deterministic fallback: try library_root/doc_path, then library_root/basename."""
    root = Path(library_root)
    p1 = root / doc_path
    if p1.exists():
        return doc_path, p1

    base = Path(doc_path).name
    p2 = root / base
    if p2.exists():
        return base, p2

    return None, None


def _artifact_path(doc_path: str, library_root: str) -> Path:
    """Return the .review.json path for a given doc_path."""
    return Path(library_root) / doc_path.replace(".md", ".review.json")


def review_artifact_exists(doc_path: str, library_root: str) -> bool:
    """Return True if a review artifact file already exists on disk."""
    p = _artifact_path(doc_path, library_root)
    return p.exists()


def load_review_artifact(doc_path: str, library_root: str) -> dict | None:
    """Load and return an existing review artifact without regenerating.
    Returns None if no artifact exists.
    """
    p = _artifact_path(doc_path, library_root)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data["_loaded_from_disk"] = True
        return data
    except Exception:
        return None


def generate_review_artifact(doc_path: str, library_root: str) -> dict:
    """Generate a non-authoritative review artifact for a document.

    Returns a dict with extracted topics, defs, suspected conflicts, and a
    recommended patch. Does NOT write to canon or modify the document.

    Always sets non_authoritative=True and requires_explicit_confirmation=True.
    See corpus_migration_doctrine §7 for artifact doctrine.
    """
    resolved_path, full_path = _resolve_doc_path(doc_path, library_root)
    if full_path is None:
        return {"error": f"File not found: {doc_path}"}

    doc_path = resolved_path

    text = full_path.read_text(encoding="utf-8", errors="replace")
    boh, body, _ = parse_frontmatter(text)

    # Resolve doc metadata from DB for enrichment
    doc_row = db.fetchone("SELECT doc_id, title, status FROM docs WHERE path = ?", (doc_path,))
    doc_id    = doc_row["doc_id"]    if doc_row else None
    doc_title = doc_row["title"]     if doc_row and doc_row.get("title") else (boh or {}).get("purpose", "")
    doc_status = doc_row["status"]   if doc_row else (boh or {}).get("status", "")

    # Extract topics from headings (deterministic; no invention beyond text)
    heading_re = re.compile(r"^#{1,4}\s+(.+)", re.MULTILINE)
    extracted_topics = [m.group(1).strip() for m in heading_re.finditer(body)]

    # Extract definitions (deterministic; parser enforces rules)
    plane_scope = []
    if boh and boh.get("scope"):
        plane_scope = boh["scope"].get("plane_scope") or []
    defs = extract_definitions(body, plane_scope)
    extracted_definitions = [{"term": d["term"], "block_hash": d["block_hash"]} for d in defs]

    # Extract variable-like patterns (existing behavior)
    var_re = re.compile(r"(?:^|\n)\s*([A-Z_][A-Z0-9_]+)\s*[=:]\s*(.+)", re.MULTILINE)
    extracted_variables = [
        {"key": m.group(1), "value": m.group(2).strip()[:100]}
        for m in var_re.finditer(body)
    ][:20]

    # Suspected conflicts: same term, different block_hash already in DB
    # Phase 9: resolve conflict target doc ids to titles + paths
    suspected_conflicts = []
    for d in defs:
        rows = db.fetchall(
            "SELECT doc_id, block_hash FROM defs WHERE term=? AND block_hash!=?",
            (d["term"], d["block_hash"]),
        )
        if rows:
            targets = []
            for r in rows:
                conflict_doc = db.fetchone(
                    "SELECT doc_id, title, path FROM docs WHERE doc_id = ?",
                    (r["doc_id"],),
                )
                targets.append({
                    "doc_id":   r["doc_id"],
                    "title":    conflict_doc["title"] if conflict_doc and conflict_doc.get("title") else r["doc_id"][:16],
                    "path":     conflict_doc["path"]  if conflict_doc else "",
                })
            suspected_conflicts.append({
                "term": d["term"],
                "conflict_with": targets,
            })

    # Recommended metadata patch (non-authoritative suggestion only — LR7)
    recommended_patch: dict = {}
    if boh:
        if not boh.get("topics") and extracted_topics:
            recommended_patch["topics"] = extracted_topics[:5]
        if not boh.get("version"):
            recommended_patch["version"] = "0.1.0"

    # Hash of normalization output (LR9)
    norm_input = json.dumps({
        "topics": extracted_topics,
        "defs": extracted_definitions,
        "vars": extracted_variables,
    }, sort_keys=True)
    normalization_output_hash = hashlib.sha256(norm_input.encode()).hexdigest()

    artifact = {
        "doc_path":   doc_path,
        "doc_id":     doc_id,
        "doc_title":  doc_title,
        "doc_status": doc_status,
        "generated_at": int(time.time()),

        # LR1, LR2, LR3 — immutable fields
        "reviewer": "BOH_WORKER_v4",
        "non_authoritative": True,           # ALWAYS TRUE — corpus_migration_doctrine §7
        "requires_explicit_confirmation": True,  # ALWAYS TRUE

        "extracted_topics": extracted_topics,
        "extracted_definitions": extracted_definitions,
        "extracted_variables": extracted_variables,
        "suspected_conflicts": suspected_conflicts,
        "recommended_metadata_patch": recommended_patch,
        "normalization_output_hash": normalization_output_hash,

        "placement_suggestion": _v4_placement_suggestion_from_meta(boh or {}),
    }

    # LR5: Write review artifact alongside source (existing behavior)
    artifact_file = _artifact_path(doc_path, library_root)
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    return artifact

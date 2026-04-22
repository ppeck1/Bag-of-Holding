"""
llm_review.py: LLM review artifact generation for Bag of Holding v0P.

Review artifacts are non-authoritative. They cannot overwrite canon automatically.
All patches require explicit user confirmation.
"""

import hashlib
import json
import re
import time
from pathlib import Path

import db
from parser import parse_frontmatter, extract_definitions


def _v4_folder_from_status(status: str) -> str:
    # Normal Python strings; safe trailing backslash via escaping.
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
    # Deterministic, no inference. Uses meta.status/meta.type only.
    status = (meta or {}).get("status")
    doc_type = (meta or {}).get("type")

    folder = _v4_folder_from_status(status or "")
    reasoning = []

    if status in {"canonical", "archived", "draft", "working"}:
        reasoning.append(f"meta.status={status} → {folder}")
    else:
        reasoning.append("meta.status missing/unknown → 01_sources\\unknown\\")

    # v4: event/ledger/person + status!=canonical → working
    if doc_type in {"event", "ledger", "person"} and status != "canonical":
        folder = "01_sources\\working\\"
        reasoning.append("type in {event,ledger,person} AND status!=canonical → 01_sources\\working\\")

    return {"recommended_folder": folder, "reasoning": reasoning}


def _resolve_doc_path(doc_path: str, library_root: str) -> tuple[str, Path] | tuple[None, None]:
    """
    Deterministic fallback:
    - try library_root/doc_path
    - if missing, try library_root/basename(doc_path)
    No invention.
    """
    root = Path(library_root)
    p1 = root / doc_path
    if p1.exists():
        return doc_path, p1

    base = Path(doc_path).name
    p2 = root / base
    if p2.exists():
        return base, p2

    return None, None


def generate_review_artifact(doc_path: str, library_root: str) -> dict:
    """
    Generate a review artifact for a document.

    Returns a dict with extracted topics, defs, suspected conflicts, and a recommended patch.
    Does NOT write to canon or modify the document.
    """
    resolved_path, full_path = _resolve_doc_path(doc_path, library_root)
    if full_path is None:
        return {"error": f"File not found: {doc_path}"}

    # Use resolved_path for output naming consistency
    doc_path = resolved_path

    text = full_path.read_text(encoding="utf-8", errors="replace")
    boh, body, _ = parse_frontmatter(text)

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
    suspected_conflicts = []
    for d in defs:
        rows = db.fetchall(
            "SELECT doc_id, block_hash FROM defs WHERE term=? AND block_hash!=?",
            (d["term"], d["block_hash"]),
        )
        if rows:
            suspected_conflicts.append({
                "term": d["term"],
                "conflict_with": [r["doc_id"] for r in rows],
            })

    # Recommended metadata patch (non-authoritative suggestion only)
    recommended_patch: dict = {}
    if boh:
        if not boh.get("topics") and extracted_topics:
            recommended_patch["topics"] = extracted_topics[:5]
        if not boh.get("version"):
            recommended_patch["version"] = "0.1.0"

    # Hash of normalization output
    norm_input = json.dumps({
        "topics": extracted_topics,
        "defs": extracted_definitions,
        "vars": extracted_variables,
    }, sort_keys=True)
    normalization_output_hash = hashlib.sha256(norm_input.encode()).hexdigest()

    artifact = {
        "doc_path": doc_path,
        "generated_at": int(time.time()),

        # v4-required fields:
        "reviewer": "BOH_WORKER_v4",
        "non_authoritative": True,
        "requires_explicit_confirmation": True,

        "extracted_topics": extracted_topics,
        "extracted_definitions": extracted_definitions,
        "extracted_variables": extracted_variables,
        "suspected_conflicts": suspected_conflicts,
        "recommended_metadata_patch": recommended_patch,
        "normalization_output_hash": normalization_output_hash,

        # v4 placement suggestion (advisory only)
        "placement_suggestion": _v4_placement_suggestion_from_meta(boh or {}),
    }

    # Write review artifact alongside source (existing behavior)
    artifact_file = Path(library_root) / (doc_path.replace(".md", ".review.json"))
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    return artifact

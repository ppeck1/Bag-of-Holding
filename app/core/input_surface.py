"""app/core/input_surface.py: Safe browser intake helpers for Bag of Holding v2.

Phase 11 addition. All filesystem writes are constrained to the managed library root.

Path-safety invariants enforced at every write:
  - All paths resolved with pathlib.Path.resolve()
  - Candidate path must be strictly inside the library root (containment check)
  - Null bytes, control characters, path traversal segments rejected at slugify stage
  - No absolute paths accepted in target_folder or filename
  - Files never overwrite existing; collision suffix (-2, -3, …) used instead

Allowed upload extensions (conservative allowlist):
  .md .txt .markdown .rst .mdx .csv .json .jsonl .html .htm .yaml .yml
  .toml .ini .cfg .conf .properties .env.example .xml .tex .bib .log .ipynb .docx
"""

from __future__ import annotations

import os
import re
import time
import uuid
import hashlib
import json
from pathlib import Path
from typing import Optional

from app.core.fs_boundary import assert_write_safe, safe_write_text

ALLOWED_EXTENSIONS = {
    ".md", ".txt", ".markdown", ".rst", ".mdx",
    ".csv", ".json", ".jsonl", ".html", ".htm",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".properties", ".env.example", ".xml", ".tex", ".bib",
    ".log", ".ipynb", ".docx",
}

TEXT_UPLOAD_EXTENSIONS = {
    ".md", ".txt", ".markdown", ".rst", ".mdx", ".tex", ".bib", ".log",
    ".toml", ".ini", ".cfg", ".conf", ".properties", ".env.example", ".xml",
}

# Bytes reserved or dangerous in filenames on Windows + POSIX
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRAVERSAL    = re.compile(r'\.\.[\\/]|^[\\/]')
_CONTROL      = re.compile(r'[\x00-\x1f\x7f]')
_UNC          = re.compile(r'^\\\\')
_DRIVE        = re.compile(r'^[a-zA-Z]:[/\\]')


def _has_frontmatter_source_hash(text: str, source_hash: str) -> bool:
    """Return true when generated BOH frontmatter records this source hash."""
    if not source_hash:
        return False
    return bool(re.search(
        rf'(?m)^\s*source_hash:\s*["\']?{re.escape(source_hash)}["\']?\s*$',
        text or "",
    ))


# ── Library root ──────────────────────────────────────────────────────────────

def get_library_root() -> Path:
    return Path(os.environ.get("BOH_LIBRARY", "./library")).resolve()


# ── Path safety helpers ───────────────────────────────────────────────────────

def safe_filename(name: str) -> str:
    """Return a safe, OS-compatible filename string (no path separators, no control chars)."""
    if not name:
        return f"doc-{uuid.uuid4().hex[:8]}"
    # Strip null bytes and control characters
    name = _CONTROL.sub("", name)
    # Strip traversal patterns
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    # Replace unsafe chars with dash
    name = _UNSAFE_CHARS.sub("-", name)
    # Collapse multiple dashes
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name[:120] or f"doc-{uuid.uuid4().hex[:8]}"


def safe_upload_relpath(name: str) -> Path:
    """Preserve browser relative paths while sanitizing each segment."""
    raw = (name or "").replace("\\", "/").lstrip("/")
    if not raw:
        return Path(f"doc-{uuid.uuid4().hex[:8]}")
    if _TRAVERSAL.search(raw) or _UNC.match(raw) or _DRIVE.match(raw) or _CONTROL.search(raw):
        raise ValueError(f"Unsafe upload filename/path: {name!r}")
    parts = [safe_filename(p) for p in raw.split("/") if p not in ("", ".", "..")]
    if not parts:
        return Path(f"doc-{uuid.uuid4().hex[:8]}")
    return Path(*parts)


def slugify_title(title: str) -> str:
    """Convert a title string to a safe, lowercase, hyphenated filename stem."""
    if not title:
        return f"untitled-{uuid.uuid4().hex[:6]}"
    slug = title.lower()
    slug = _CONTROL.sub("", slug)
    slug = re.sub(r"[^a-z0-9\s\-_]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:80] or f"doc-{uuid.uuid4().hex[:6]}"


def safe_subpath(target_folder: str) -> Path:
    """Return a safe relative path segment for a target subfolder.

    Raises ValueError if the result would escape the library root.
    """
    if not target_folder:
        target_folder = "notes"
    # Reject absolute paths, UNC paths, drive roots, traversal
    if _TRAVERSAL.search(target_folder):
        raise ValueError(f"Path traversal rejected in target_folder: {target_folder!r}")
    if _UNC.match(target_folder):
        raise ValueError(f"UNC path rejected: {target_folder!r}")
    if _DRIVE.match(target_folder):
        raise ValueError(f"Absolute drive path rejected: {target_folder!r}")
    if _CONTROL.search(target_folder):
        raise ValueError(f"Control characters in target_folder: {target_folder!r}")

    # Sanitize each segment
    parts = re.split(r"[/\\]", target_folder)
    safe_parts = []
    for p in parts:
        p = _UNSAFE_CHARS.sub("-", p).strip("-")
        if p and p != "..":
            safe_parts.append(p)

    # WO-2 mutation isolation: the promoted_intake subtree is managed exclusively by the
    # governed promotion service — ordinary uploads/notes may not write into it.
    if safe_parts and safe_parts[0].lower() == "promoted_intake":
        raise ValueError("promoted_intake_managed_document: "
                         "target_folder may not address the managed promotion subtree")

    return Path(*safe_parts) if safe_parts else Path("notes")


def _assert_inside_root(candidate: Path, root: Path) -> None:
    """Raise ValueError if candidate is not strictly inside root."""
    candidate = candidate.resolve()
    root = root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(
            f"Path escape detected: '{candidate}' is outside library root '{root}'"
        )


def next_available_path(path: Path) -> Path:
    """Return path if it doesn't exist, else path-2, path-3, …"""
    if not path.exists():
        return path
    stem   = path.stem
    suffix = path.suffix
    parent = path.parent
    n = 2
    while True:
        candidate = parent / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1
        if n > 999:
            return parent / f"{stem}-{uuid.uuid4().hex[:6]}{suffix}"


def _deterministic_upload_doc_id(rel_path: str, source_hash: str) -> str:
    seed = f"{rel_path}\n{source_hash}".encode("utf-8", errors="replace")
    return f"doc-{hashlib.sha256(seed).hexdigest()[:12]}"


def _upload_extension(path: Path) -> str:
    suffixes = [s.lower() for s in path.suffixes]
    for i in range(len(suffixes)):
        candidate = "".join(suffixes[i:])
        if candidate in ALLOWED_EXTENSIONS:
            return candidate
    return path.suffix.lower()


# ── Frontmatter helpers ───────────────────────────────────────────────────────

def has_boh_frontmatter(text: str) -> bool:
    """Return True if the text already starts with valid BOH frontmatter."""
    return text.lstrip().startswith("---") and "boh:" in text[:600]


def build_boh_frontmatter(title: str, topics: list[str],
                           doc_id: Optional[str] = None,
                           doc_type: str = "note",
                           project: str = "Scratch Capture",
                           document_class: str = "note",
                           status: str = "draft",
                           canonical_layer: str = "supporting",
                           source_hash: str = "",
                           provenance: Optional[dict] = None) -> str:
    """Build conservative default BOH frontmatter for browser-created docs."""
    def yq(value: object) -> str:
        return json.dumps(str(value or ""), ensure_ascii=False)

    if not doc_id:
        doc_id = f"doc-{uuid.uuid4().hex[:8]}"
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    provenance = provenance or {"mode": "scratch_capture", "source": "browser"}
    if not topics:
        topics_block = "  topics: []"
    else:
        topics_block = "  topics:\n" + "\n".join(f"    - {yq(t)}" for t in topics[:20])

    return f"""---
boh:
  id: {yq(doc_id)}
  document_id: {yq(doc_id)}
  type: {yq(doc_type)}
  document_class: {yq(document_class)}
  project: {yq(project)}
  purpose: {yq(title[:120])}
  title: {yq(title[:120])}
  {topics_block.lstrip()}
  status: {yq(status)}
  state: inbox
  requires_review: false
  authority_state: quarantined
  review_state: unassigned
  source_hash: {yq(source_hash)}
  provenance:
    mode: {yq(provenance.get("mode", "scratch_capture"))}
    source: {yq(provenance.get("source", "browser"))}
  version: "0.0.1"
  updated: "{now_iso}"
  scope:
    plane_scope: []
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: observe
    operator_intent: capture
    next_operator: null
---

"""


# ── Save helpers ──────────────────────────────────────────────────────────────

def save_markdown_note(title: str, body: str,
                       topics: Optional[list[str]] = None,
                       target_folder: str = "notes") -> dict:
    """Save a browser-created Markdown note into the managed library.

    Never overwrites existing files.
    Always uses conservative draft status.
    Returns: {"doc_id": str, "path": str, "indexed": bool, "lint_errors": list}
    """
    topics = topics or []
    root   = get_library_root()
    folder = safe_subpath(target_folder)
    dest_dir = (root / folder).resolve()
    _assert_inside_root(dest_dir, root)

    slug      = slugify_title(title)
    doc_id    = f"doc-{uuid.uuid4().hex[:8]}"
    file_name = next_available_path(dest_dir / f"{slug}.md")
    _assert_inside_root(file_name, root)

    body_hash = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()
    frontmatter = build_boh_frontmatter(title, topics, doc_id=doc_id, source_hash=body_hash)
    full_content = frontmatter + body

    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_write_text(
        file_name,
        full_content,
        root,
        entity_type="human",
        entity_id="browser",
        doc_id=doc_id,
    )

    # Audit
    try:
        from app.core.audit import log_event
        log_event("save", actor_type="human", actor_id="browser",
                  doc_id=doc_id,
                  detail=f'{{"path":"{file_name.relative_to(root)!s}","source":"input_surface"}}')
    except Exception:
        pass

    # Index
    lint_errors: list[str] = []
    indexed = False
    try:
        from app.services.indexer import index_file
        result = index_file(file_name, root)
        lint_errors = result.get("lint_errors", [])
        indexed = result.get("indexed", False)
    except Exception as exc:
        lint_errors = [f"Index error: {exc}"]

    return {
        "doc_id":     doc_id,
        "path":       file_name.relative_to(root).as_posix(),
        "indexed":    indexed,
        "lint_errors": lint_errors,
    }


def save_upload(filename: str, content_bytes: bytes,
                target_folder: str = "imports",
                intake_mode: str = "scratch",
                metadata: Optional[dict] = None) -> dict:
    """Save an uploaded file into the managed library.

    Checks extension allowlist, sanitizes filename, prevents overwrite.
    Adds BOH frontmatter to .md/.txt files that lack it.
    Returns: {"filename": str, "path": str, "indexed": bool} | {"filename": str, "reason": str}
    """
    root = get_library_root()

    # Extension check
    original_name = safe_upload_relpath(filename)
    ext = _upload_extension(original_name)
    if ext not in ALLOWED_EXTENSIONS:
        return {"filename": filename, "reason": f"unsupported extension: {ext or '(none)'}"}

    if not content_bytes:
        return {"filename": filename, "reason": "empty file rejected"}

    intake_mode = (intake_mode or "scratch").strip().lower()
    metadata = metadata or {}
    source_hash = hashlib.sha256(content_bytes).hexdigest()
    if intake_mode in {"governed", "governed_entry"}:
        from app.core.metadata_contract import REQUIRED_GOVERNED_FIELDS
        if not metadata.get("source_hash"):
            metadata["source_hash"] = source_hash
        if not metadata.get("document_id"):
            metadata["document_id"] = f"doc-{uuid.uuid4().hex[:8]}"
        missing = [f for f in REQUIRED_GOVERNED_FIELDS if not metadata.get(f)]
        if missing:
            return {
                "filename": filename,
                "reason": "governed import rejected: missing " + ", ".join(missing),
                "validation_errors": [{"field": f, "code": "required"} for f in missing],
            }
        target_folder = target_folder or f"{metadata.get('project')}/{metadata.get('document_class')}"
    else:
        target_folder = target_folder or "scratch"

    folder   = safe_subpath(target_folder)
    dest_dir = (root / folder).resolve()
    _assert_inside_root(dest_dir, root)
    dest_dir.mkdir(parents=True, exist_ok=True)

    preferred_file = dest_dir / original_name
    _assert_inside_root(preferred_file, root)
    preferred_rel = preferred_file.relative_to(root).as_posix()
    write_bytes = content_bytes
    write_text: str | None = None

    # Optionally inject BOH frontmatter for text files that lack it. Build the
    # exact persisted content before comparing hashes so unchanged re-uploads
    # are idempotent even when BOH generated the header.
    if ext in TEXT_UPLOAD_EXTENSIONS:
        text = content_bytes.decode("utf-8", errors="replace")
        if not has_boh_frontmatter(text):
            stem = original_name.stem.replace("-", " ").replace("_", " ").title()
            if intake_mode in {"governed", "governed_entry"}:
                doc_id = metadata.get("document_id") or _deterministic_upload_doc_id(preferred_rel, source_hash)
                fm = build_boh_frontmatter(
                    stem, [],
                    doc_id=doc_id,
                    doc_type=metadata.get("document_class", "reference"),
                    project=metadata.get("project", ""),
                    document_class=metadata.get("document_class", "reference"),
                    status=metadata.get("status", "draft"),
                    canonical_layer=metadata.get("canonical_layer", "supporting"),
                    source_hash=metadata.get("source_hash") or source_hash,
                    provenance={"mode": "governed_entry", "source": metadata.get("provenance", "upload")},
                )
            else:
                fm = build_boh_frontmatter(
                    stem,
                    [],
                    doc_id=_deterministic_upload_doc_id(preferred_rel, source_hash),
                    source_hash=source_hash,
                    provenance={"mode": "bulk_import", "source": metadata.get("provenance", "upload")},
                )
            text = fm + text
        write_text = text
        write_bytes = text.encode("utf-8")

    if preferred_file.exists():
        existing_bytes = preferred_file.read_bytes()
        existing_hash = hashlib.sha256(existing_bytes).hexdigest()
        existing_text = existing_bytes.decode("utf-8", errors="replace") if ext in TEXT_UPLOAD_EXTENSIONS else ""
        same_text_content = bool(write_text is not None and existing_text.replace("\r\n", "\n") == write_text.replace("\r\n", "\n"))
        same_generated_source = _has_frontmatter_source_hash(existing_text, source_hash)
        if existing_hash == hashlib.sha256(write_bytes).hexdigest() or same_text_content or same_generated_source:
            rel = preferred_rel
            try:
                from app.db import connection as db
                row = db.fetchone("SELECT doc_id FROM docs WHERE path = ?", (rel,))
                doc_id = row["doc_id"] if row else None
            except Exception:
                doc_id = None
            return {
                "filename": filename,
                "path": rel,
                "indexed": False,
                "skipped": True,
                "skip_reason": "unchanged",
                "doc_id": doc_id,
                "action": "skipped_unchanged",
                "source_hash": source_hash,
            }

    dest_file = next_available_path(preferred_file)
    _assert_inside_root(dest_file, root)
    dest_file.parent.mkdir(parents=True, exist_ok=True)

    if ext in TEXT_UPLOAD_EXTENSIONS:
        try:
            safe_write_text(
                dest_file,
                write_text or content_bytes.decode("utf-8", errors="replace"),
                root,
                entity_type="human",
                entity_id="browser",
            )
        except Exception:
            assert_write_safe(dest_file, root, entity_type="human", entity_id="browser")
            dest_file.write_bytes(content_bytes)
    else:
        assert_write_safe(dest_file, root, entity_type="human", entity_id="browser")
        dest_file.write_bytes(write_bytes)

    # Index
    lint_errors: list[str] = []
    indexed = False
    doc_id  = None
    if ext in ALLOWED_EXTENSIONS:
        try:
            from app.services.indexer import index_file
            result   = index_file(dest_file, root)
            lint_errors = result.get("lint_errors", [])
            indexed  = result.get("indexed", False)
            doc_id   = result.get("doc_id")
        except Exception as exc:
            lint_errors = [f"Index error: {exc}"]

    try:
        from app.core.audit import log_event
        import json
        log_event("import", actor_type="human", actor_id="browser",
                  doc_id=doc_id,
                  detail=json.dumps({
                      "path": dest_file.relative_to(root).as_posix(),
                      "source": "upload",
                      "indexed": indexed,
                      "source_hash": source_hash,
                  }))
    except Exception:
        pass

    return {
        "filename":    dest_file.name,
        "path":        dest_file.relative_to(root).as_posix(),
        "indexed":     indexed,
        "doc_id":      doc_id,
        "lint_errors": lint_errors,
        "action":      "imported",
        "source_hash": source_hash,
    }

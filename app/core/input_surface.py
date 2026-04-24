"""app/core/input_surface.py: Safe browser intake helpers for Bag of Holding v2.

Phase 11 addition. All filesystem writes are constrained to the managed library root.

Path-safety invariants enforced at every write:
  - All paths resolved with pathlib.Path.resolve()
  - Candidate path must be strictly inside the library root (containment check)
  - Null bytes, control characters, path traversal segments rejected at slugify stage
  - No absolute paths accepted in target_folder or filename
  - Files never overwrite existing; collision suffix (-2, -3, …) used instead

Allowed upload extensions (conservative allowlist):
  .md .txt .markdown .rst .csv .json .html .htm .yaml .yml
"""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

ALLOWED_EXTENSIONS = {
    ".md", ".txt", ".markdown", ".rst",
    ".csv", ".json", ".html", ".htm",
    ".yaml", ".yml",
}

# Bytes reserved or dangerous in filenames on Windows + POSIX
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRAVERSAL    = re.compile(r'\.\.[\\/]|^[\\/]')
_CONTROL      = re.compile(r'[\x00-\x1f\x7f]')
_UNC          = re.compile(r'^\\\\')
_DRIVE        = re.compile(r'^[a-zA-Z]:[/\\]')


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


# ── Frontmatter helpers ───────────────────────────────────────────────────────

def has_boh_frontmatter(text: str) -> bool:
    """Return True if the text already starts with valid BOH frontmatter."""
    return text.lstrip().startswith("---") and "boh:" in text[:600]


def build_boh_frontmatter(title: str, topics: list[str],
                           doc_id: Optional[str] = None,
                           doc_type: str = "note") -> str:
    """Build conservative default BOH frontmatter for browser-created docs."""
    if not doc_id:
        doc_id = f"doc-{uuid.uuid4().hex[:8]}"
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    topics_yaml = "\n".join(f"    - {t}" for t in topics[:20]) if topics else "    []"
    if not topics:
        topics_yaml = "    []"
        topics_block = "  topics: []"
    else:
        topics_block = "  topics:\n" + "\n".join(f"    - {t}" for t in topics[:20])

    return f"""---
boh:
  id: {doc_id}
  type: {doc_type}
  purpose: {title[:120]}
  {topics_block.lstrip()}
  status: draft
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

    frontmatter = build_boh_frontmatter(title, topics, doc_id=doc_id)
    full_content = frontmatter + body

    dest_dir.mkdir(parents=True, exist_ok=True)
    file_name.write_text(full_content, encoding="utf-8")

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
        "path":       str(file_name.relative_to(root)),
        "indexed":    indexed,
        "lint_errors": lint_errors,
    }


def save_upload(filename: str, content_bytes: bytes,
                target_folder: str = "imports") -> dict:
    """Save an uploaded file into the managed library.

    Checks extension allowlist, sanitizes filename, prevents overwrite.
    Adds BOH frontmatter to .md/.txt files that lack it.
    Returns: {"filename": str, "path": str, "indexed": bool} | {"filename": str, "reason": str}
    """
    root = get_library_root()

    # Extension check
    original_name = Path(safe_filename(filename))
    ext = original_name.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {"filename": filename, "reason": f"unsupported extension: {ext or '(none)'}"}

    if not content_bytes:
        return {"filename": filename, "reason": "empty file rejected"}

    folder   = safe_subpath(target_folder)
    dest_dir = (root / folder).resolve()
    _assert_inside_root(dest_dir, root)
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_file = next_available_path(dest_dir / original_name.name)
    _assert_inside_root(dest_file, root)

    # Optionally inject BOH frontmatter for text files that lack it
    if ext in (".md", ".txt", ".markdown", ".rst"):
        try:
            text = content_bytes.decode("utf-8", errors="replace")
            if not has_boh_frontmatter(text):
                stem = original_name.stem.replace("-", " ").replace("_", " ").title()
                fm   = build_boh_frontmatter(stem, [])
                text = fm + text
            dest_file.write_text(text, encoding="utf-8")
        except Exception:
            dest_file.write_bytes(content_bytes)
    else:
        dest_file.write_bytes(content_bytes)

    # Audit
    try:
        from app.core.audit import log_event
        log_event("save", actor_type="human", actor_id="browser",
                  detail=f'{{"path":"{dest_file.relative_to(root)!s}","source":"upload"}}')
    except Exception:
        pass

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

    return {
        "filename":    dest_file.name,
        "path":        str(dest_file.relative_to(root)),
        "indexed":     indexed,
        "doc_id":      doc_id,
        "lint_errors": lint_errors,
    }

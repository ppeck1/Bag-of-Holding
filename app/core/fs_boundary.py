"""app/core/fs_boundary.py: Filesystem write boundary enforcement for Bag of Holding v2.

Phase 10 hardening (architectural tension 2).

The DB is the control plane; the filesystem is the data plane.

All filesystem write operations must pass through this module.
No other module should write to the filesystem directly, except:
  - indexer.py  (reads only — filesystem → DB)
  - execution.py (writes to workspace only, inside _run_python / _run_shell)
  - reviewer.py  (writes .review.json artifacts — must call assert_write_safe)

This module provides:
  - assert_write_safe(path, entity_type, entity_id) — raises if write is unsafe
  - safe_write_text(path, content, entity_type, entity_id) — write + audit
  - safe_mkdir(path, entity_type, entity_id) — mkdir + audit
  - canonical_path_for(doc, library_root) — derive path without side effects
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

from app.core import audit


# ── Protected path patterns ───────────────────────────────────────────────────

PROTECTED_PREFIXES = ("canon/", "canon\\")
PROTECTED_SUBSTRINGS = ("/canon/", "\\canon\\")


def is_protected_path(path: str | Path) -> bool:
    """Return True if the path resolves inside a protected directory.

    Called before any filesystem write. Both forward and backslash are checked
    so it works on Windows paths embedded in DB records.
    """
    norm = str(path).replace("\\", "/").lower()
    if norm.startswith("canon/"):
        return True
    return any(s in norm for s in ("/canon/",))


def is_within_root(path: Path, root: Path) -> bool:
    """Return True if path is within (or equal to) root. Prevents path traversal."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ── Write gate ────────────────────────────────────────────────────────────────

class WriteViolation(Exception):
    """Raised when a filesystem write would violate a governance rule."""
    def __init__(self, message: str, reason: str = ""):
        super().__init__(message)
        self.reason = reason


def assert_write_safe(
    path: str | Path,
    library_root: str | Path,
    entity_type: str = "human",
    entity_id: str = "*",
    doc_id: Optional[str] = None,
) -> None:
    """Gate function — raises WriteViolation if this write should be denied.

    Checks in order:
      1. Path traversal: path must be inside library_root
      2. Canon path protection: path must not be inside canon/ directory
      3. DB-status canon protection: if doc_id given, doc must not be canonical
      4. Policy: entity must have can_write on the workspace (library_root)

    Call this before any file.write_text() / mkdir() / unlink().
    """
    p    = Path(path)
    root = Path(library_root).resolve()

    # 1. Path traversal
    if not is_within_root(p, root):
        raise WriteViolation(
            f"Path traversal denied: '{p}' is outside library root '{root}'.",
            reason="path_traversal",
        )

    # 2. Protected directory
    rel = str(p.resolve().relative_to(root)).replace("\\", "/")
    if is_protected_path(rel):
        raise WriteViolation(
            f"Canon protection: path '{rel}' is inside a protected directory.",
            reason="protected_path",
        )

    # 3. Doc-level canon protection
    if doc_id:
        from app.db import connection as db
        row = db.fetchone("SELECT status FROM docs WHERE doc_id = ?", (doc_id,))
        if row and row.get("status") == "canonical":
            raise WriteViolation(
                f"Canon protection: document '{doc_id}' has status=canonical "
                "and cannot be overwritten.",
                reason="canonical_doc",
            )

    # 4. Policy check
    from app.core.governance import get_effective_policy
    policy = get_effective_policy(str(root), entity_type, entity_id)
    if not policy.get("can_write"):
        raise WriteViolation(
            f"Write permission denied for {entity_type}:{entity_id} "
            f"on workspace '{root}'.",
            reason="permission_denied",
        )


def safe_write_text(
    path: str | Path,
    content: str,
    library_root: str | Path,
    entity_type: str = "human",
    entity_id: str = "*",
    doc_id: Optional[str] = None,
    encoding: str = "utf-8",
) -> dict:
    """Write text to a file after passing all governance checks.

    Returns: {"written": True, "path": str, "hash": str}
    Raises: WriteViolation if any check fails.
    """
    p = Path(path)
    assert_write_safe(p, library_root, entity_type, entity_id, doc_id)

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)

    file_hash = hashlib.sha256(content.encode(encoding)).hexdigest()[:32]

    audit.log_event(
        event_type="save",
        actor_type=entity_type,
        actor_id=entity_id,
        doc_id=doc_id,
        workspace=str(Path(library_root).resolve()),
        detail=f'{{"path": "{p}", "hash": "{file_hash}"}}',
    )

    return {"written": True, "path": str(p), "hash": file_hash}


def safe_mkdir(
    path: str | Path,
    library_root: str | Path,
    entity_type: str = "human",
    entity_id: str = "*",
) -> None:
    """Create a directory after passing write governance checks."""
    p = Path(path)
    assert_write_safe(p, library_root, entity_type, entity_id)
    p.mkdir(parents=True, exist_ok=True)


def canonical_path_for(doc: dict, library_root: str | Path) -> Path:
    """Return the expected on-disk path for a document without touching the filesystem."""
    root = Path(library_root).resolve()
    if doc.get("path"):
        return root / doc["path"]
    # Derive from doc_id
    safe_name = (doc.get("doc_id") or "unknown").replace("/", "-").replace(" ", "-").lower()
    return root / f"{safe_name}.md"

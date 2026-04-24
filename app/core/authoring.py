"""app/core/authoring.py: Internal document authoring layer for Bag of Holding v2.

Phase 10 addition. Provides create/edit/save workflow for documents.

Enforcement rules (hardened):
  - Canon protection is centralized via is_canonical_path() — checked at every write path
  - Canonical docs cannot be overwritten by any route (not just authoring)
  - Draft source_hash guards against silent overwrite conflicts
  - check_write_permission() enforced before save
  - Rubrix and Daenary remain unchanged by editing — they are updated via frontmatter
"""

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Optional

import yaml

from app.db import connection as db
from app.services.parser import parse_frontmatter_full
from app.services.indexer import extract_summary


# ── Canon / workspace protection (centralized) ────────────────────────────────

PROTECTED_STATUS = {"canonical"}
PROTECTED_SUBPATHS = ("canon/", "/canon/")  # conventional protected directories


def is_canonical_doc(doc_id: str) -> bool:
    """Return True if the document in the DB has canonical status."""
    row = db.fetchone("SELECT status FROM docs WHERE doc_id = ?", (doc_id,))
    return bool(row and row.get("status") in PROTECTED_STATUS)


def is_canonical_path(path: str) -> bool:
    """Return True if the file path is inside a conventionally protected directory."""
    norm = path.replace("\\", "/").lower()
    return any(p in norm for p in PROTECTED_SUBPATHS)


def assert_not_canon(doc_id: str, path: Optional[str] = None) -> Optional[dict]:
    """Return an error dict if the doc is canonical; None if write is permitted.

    Checks both DB status AND path convention so protection works even when
    the DB is stale (e.g. during a re-index conflict).
    """
    if is_canonical_doc(doc_id):
        return {
            "error": "Canon protection: canonical documents cannot be overwritten directly. "
                     "Create a new draft or use the proposal workflow.",
            "canon_protected": True,
        }
    if path and is_canonical_path(path):
        return {
            "error": f"Canon protection: path '{path}' is inside a protected directory. "
                     "Write access denied.",
            "canon_protected": True,
        }
    return None


# ── Draft CRUD ────────────────────────────────────────────────────────────────

def _file_hash(file_path: Path) -> str:
    """SHA-256 of the file on disk. Used to detect external modifications."""
    try:
        return hashlib.sha256(file_path.read_bytes()).hexdigest()[:32]
    except Exception:
        return ""


def get_draft(doc_id: str) -> dict | None:
    """Return the in-memory draft for a doc, or None if no draft exists."""
    return db.fetchone("SELECT * FROM doc_drafts WHERE doc_id = ?", (doc_id,))


def create_draft(doc_id: str, body_text: str, frontmatter_json: str,
                 title: str, summary: str,
                 source_hash: str = "") -> dict:
    """Create or replace a draft for a document.

    source_hash is the SHA-256 of the file at open time.
    It is compared at save time to detect external modifications.
    """
    now = int(time.time())
    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO doc_drafts
              (doc_id, body_text, frontmatter_json, title, summary,
               dirty, created_ts)
            VALUES (?,?,?,?,?,1,?)
            """,
            (doc_id, body_text, frontmatter_json, title, summary, now),
        )
        conn.commit()
    finally:
        conn.close()
    draft = get_draft(doc_id)
    # Store source_hash in memory (session-level; not in schema to keep it simple)
    if draft:
        draft["_source_hash"] = source_hash
    return draft


def update_draft(doc_id: str, body_text: Optional[str] = None,
                 frontmatter_json: Optional[str] = None,
                 title: Optional[str] = None,
                 summary: Optional[str] = None) -> dict | None:
    """Partial update of a draft. Only supplied fields are changed."""
    draft = get_draft(doc_id)
    if not draft:
        return None

    new_body    = body_text        if body_text        is not None else draft["body_text"]
    new_fm      = frontmatter_json if frontmatter_json is not None else draft["frontmatter_json"]
    new_title   = title            if title            is not None else draft["title"]
    new_summary = summary          if summary          is not None else draft["summary"]

    conn = db.get_conn()
    try:
        conn.execute(
            """
            UPDATE doc_drafts
            SET body_text=?, frontmatter_json=?, title=?, summary=?, dirty=1
            WHERE doc_id=?
            """,
            (new_body, new_fm, new_title, new_summary, doc_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_draft(doc_id)


def discard_draft(doc_id: str):
    """Discard the in-memory draft without saving."""
    db.execute("DELETE FROM doc_drafts WHERE doc_id = ?", (doc_id,))


def regenerate_summary(doc_id: str) -> str:
    """Deterministically regenerate the draft summary from current body_text."""
    draft = get_draft(doc_id)
    if not draft:
        return ""
    new_summary = extract_summary(draft["body_text"] or "")
    update_draft(doc_id, summary=new_summary)
    return new_summary


# ── New document creation ─────────────────────────────────────────────────────

def new_doc_template(doc_type: str = "note", status: str = "draft",
                     title: str = "") -> dict:
    """Return a starter template for a new document.

    Does not write to disk. Creates a transient draft with a fresh UUID.
    """
    new_id = str(uuid.uuid4())[:8]
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    fm = {
        "boh": {
            "id": f"doc-{new_id}",
            "type": doc_type,
            "purpose": title or f"New {doc_type}",
            "topics": [],
            "status": status,
            "version": "0.1.0",
            "updated": now_iso,
            "scope": {"plane_scope": [], "field_scope": [], "node_scope": []},
            "rubrix": {"operator_state": "observe", "operator_intent": "capture"},
        }
    }
    return {
        "doc_id":           f"doc-{new_id}",
        "frontmatter_json": json.dumps(fm, indent=2),
        "body_text":        "",
        "title":            title or f"New {doc_type}",
        "summary":          "",
        "is_new":           True,
    }


# ── Save to disk ──────────────────────────────────────────────────────────────

def _build_markdown(frontmatter_json: str, body_text: str) -> str:
    """Compose a full markdown file from frontmatter dict (JSON string) + body."""
    try:
        fm_dict = json.loads(frontmatter_json)
    except (json.JSONDecodeError, TypeError):
        fm_dict = {}
    yaml_str = yaml.dump(fm_dict, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{yaml_str}\n---\n\n{body_text}"


def save_draft_to_disk(doc_id: str, library_root: str,
                       entity_type: str = "human",
                       entity_id: str = "*",
                       source_hash: Optional[str] = None) -> dict:
    """Write the draft to its markdown file and re-index it.

    Enforcement:
      1. Canon protection — canonical docs and protected paths cannot be saved over.
      2. Write permission check — entity_type / entity_id must have can_write on workspace.
      3. Source hash check — if source_hash is provided, compare to current file to detect
         external modifications since the draft was opened.

    Returns: {"saved": True, "path": ..., "lint_errors": [...]} on success
             {"error": "...", "canon_protected"?: True} on failure
    """
    draft = get_draft(doc_id)
    if not draft:
        return {"error": f"No draft found for doc_id={doc_id}"}

    # ── Enforcement 1: Canon protection (also enforced inside fs_boundary) ───────
    # Checked here early for a clear error message before path resolution.
    existing = db.fetchone("SELECT status, path FROM docs WHERE doc_id = ?", (doc_id,))
    canon_err = assert_not_canon(
        doc_id,
        path=existing.get("path") if existing else None,
    )
    if canon_err:
        return canon_err

    # ── Enforcement 2: Write permission is enforced inside fs_boundary ───────────
    # (get_effective_policy is called by safe_write_text → assert_write_safe)

    # Determine file path
    root = Path(library_root).resolve()
    if existing and existing.get("path"):
        file_path = root / existing["path"]
    else:
        try:
            fm = json.loads(draft["frontmatter_json"])
            boh_id = fm.get("boh", {}).get("id") or doc_id
        except Exception:
            boh_id = doc_id
        safe_name = boh_id.replace("/", "-").replace(" ", "-").lower()
        file_path = root / f"{safe_name}.md"

    # ── Enforcement 3: Source hash check (detect external modification) ───────
    if source_hash and file_path.exists():
        current_hash = _file_hash(file_path)
        if current_hash and current_hash != source_hash:
            return {
                "error": "File was modified externally since this draft was opened. "
                         "Reload the document before saving to avoid overwriting changes.",
                "external_modification": True,
                "current_hash": current_hash,
                "draft_source_hash": source_hash,
            }

    # Write file — all governance checks delegated to fs_boundary
    from app.core.fs_boundary import safe_write_text, WriteViolation
    content = _build_markdown(draft["frontmatter_json"], draft["body_text"])
    try:
        write_result = safe_write_text(
            file_path, content, root,
            entity_type=entity_type,
            entity_id=entity_id,
            doc_id=doc_id,
        )
    except WriteViolation as e:
        err: dict = {"error": str(e)}
        if e.reason == "path_traversal":
            err["path_traversal"] = True
        elif e.reason in ("protected_path", "canonical_doc"):
            err["canon_protected"] = True
        elif e.reason == "permission_denied":
            err["permission_denied"] = True
        return err

    # Re-index after successful write
    rel_path = write_result["path"]
    try:
        from app.services.indexer import index_file
        result = index_file(file_path, root)
    except Exception as e:
        result = {"lint_errors": [f"Index error: {e}"]}

    # Mark draft as saved
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE doc_drafts SET dirty=0, saved_ts=? WHERE doc_id=?",
            (int(time.time()), doc_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "saved": True,
        "path": rel_path,
        "doc_id": doc_id,
        "new_hash": write_result.get("hash", ""),
        "lint_errors": result.get("lint_errors", []),
    }


# ── Permission check helpers (convenience wrappers) ───────────────────────────

def check_write_permission(workspace: str, entity_type: str = "human",
                            entity_id: str = "*") -> bool:
    """Return True if the entity has write permission on the workspace."""
    from app.core.governance import get_effective_policy
    policy = get_effective_policy(workspace, entity_type, entity_id)
    return bool(policy.get("can_write"))


def check_promote_permission(workspace: str, entity_type: str = "human",
                              entity_id: str = "*") -> bool:
    """Return True if the entity can promote a document to canon in this workspace."""
    # Models can never promote — hardcoded invariant
    if entity_type == "model":
        return False
    from app.core.governance import get_effective_policy
    policy = get_effective_policy(workspace, entity_type, entity_id)
    return bool(policy.get("can_promote"))

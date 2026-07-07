"""app/api/routes/authoring.py: Document authoring endpoints for Bag of Holding v2.

Phase 10 addition.

  GET  /api/editor/{doc_id}           — load document into editor (creates draft)
  GET  /api/editor/new                — blank document template
  PATCH /api/editor/{doc_id}          — update draft fields
  POST /api/editor/{doc_id}/save      — save draft to disk + re-index
  DELETE /api/editor/{doc_id}/draft   — discard unsaved draft
  POST /api/editor/{doc_id}/summary/regenerate — regenerate summary deterministically
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db import connection as db
from app.services.parser import parse_frontmatter_full
from app.core import authoring, audit
from app.core.auth import require_operator
from app.core.fs_boundary import PathBoundaryViolation, get_library_root, resolve_under_library

router = APIRouter(prefix="/api")
LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")


class DraftUpdate(BaseModel):
    body_text:        Optional[str] = None
    frontmatter_json: Optional[str] = None
    title:            Optional[str] = None
    summary:          Optional[str] = None


@router.get("/editor/new", summary="Return a blank document template")
def new_document(doc_type: str = Query("note"), title: str = Query("")):
    """Return a starter template for a new document without writing to disk."""
    return authoring.new_doc_template(doc_type=doc_type, title=title)


@router.get("/editor/{doc_id}", summary="Load a document into the editor")
def load_editor(doc_id: str, library_root: Optional[str] = Query(None)):
    """Load a document into the editor, creating a draft if one doesn't exist.

    Reads the file from disk, parses frontmatter, and creates an in-memory draft.
    Returns the draft state.
    """
    doc = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    # WO-2 audit item 2: the open editor-load read returns full file text — promoted docs are
    # env-gated here too (fail-closed), same posture as /api/docs/{id} and the reader route.
    from app.core import promoted_exposure
    if promoted_exposure.is_promoted_row(doc) and not promoted_exposure.env_gate_open():
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    if library_root:
        raise HTTPException(status_code=403, detail="caller-supplied library_root is not allowed")
    root = str(get_library_root())

    # Check for existing draft
    existing_draft = authoring.get_draft(doc_id)
    if existing_draft:
        return {**existing_draft, "_source": "existing_draft"}

    try:
        file_path = resolve_under_library(doc["path"])
    except PathBoundaryViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404,
                            detail=f"File not found: {doc['path']}")

    text = file_path.read_text(encoding="utf-8", errors="replace")
    import json, hashlib
    source_hash = hashlib.sha256(text.encode()).hexdigest()[:32]
    boh, raw_header, body, _ = parse_frontmatter_full(text)
    fm_json = json.dumps(raw_header, indent=2, ensure_ascii=False)

    draft = authoring.create_draft(
        doc_id=doc_id,
        body_text=body,
        frontmatter_json=fm_json,
        title=doc.get("title") or "",
        summary=doc.get("summary") or "",
        source_hash=source_hash,
    )

    audit.log_event(event_type="edit", actor_type="human", doc_id=doc_id,
                    workspace=root)

    return {**draft, "_source": "loaded_from_disk", "source_hash": source_hash}


@router.patch("/editor/{doc_id}", summary="Update draft fields")
def update_draft(doc_id: str, update: DraftUpdate, _operator: str = Depends(require_operator)):
    """Partial update of a document draft. Only supplied fields are changed."""
    if not authoring.get_draft(doc_id):
        raise HTTPException(status_code=404,
                            detail=f"No draft found for {doc_id}. Call GET /api/editor/{doc_id} first.")

    draft = authoring.update_draft(
        doc_id=doc_id,
        body_text=update.body_text,
        frontmatter_json=update.frontmatter_json,
        title=update.title,
        summary=update.summary,
    )
    return draft


@router.post("/editor/{doc_id}/save", summary="Save draft to disk and re-index")
def save_draft(
    doc_id:      str,
    library_root: Optional[str] = Query(None),
    entity_type:  str           = Query("operator"),
    entity_id:    str           = Query("local_operator"),
    source_hash:  Optional[str] = Query(None),
    _operator:    str           = Depends(require_operator),
):
    """Write the draft to its markdown file and trigger re-indexing.

    Enforcement:
      - Canon protection: canonical documents cannot be saved over directly.
      - Write permission: entity_type/entity_id must have can_write on workspace.
      - Source hash: if provided, compared to current disk state to detect
        external modifications since the draft was opened.

    Returns save result including any lint errors from re-indexing.
    """
    if library_root:
        raise HTTPException(status_code=403, detail="caller-supplied library_root is not allowed")
    root = str(get_library_root())
    result = authoring.save_draft_to_disk(
        doc_id,
        root,
        entity_type=entity_type,
        entity_id=entity_id,
        source_hash=source_hash,
    )

    if "error" in result:
        if result.get("canon_protected"):
            status_code = 403
        elif result.get("permission_denied"):
            status_code = 403
        elif result.get("external_modification"):
            status_code = 409
        elif result.get("path_traversal"):
            status_code = 400
        elif "No draft found" in result.get("error", ""):
            status_code = 404
        else:
            status_code = 500
        raise HTTPException(status_code=status_code, detail=result["error"])

    audit.log_event(event_type="save", actor_type=entity_type, actor_id=entity_id,
                    doc_id=doc_id, workspace=root,
                    detail=f'{{"path": "{result.get("path", "")}"}}')
    return result


@router.delete("/editor/{doc_id}/draft", summary="Discard unsaved draft")
def discard_draft(doc_id: str, _operator: str = Depends(require_operator)):
    """Discard the in-memory draft without saving. File on disk is unchanged."""
    if not authoring.get_draft(doc_id):
        raise HTTPException(status_code=404,
                            detail=f"No draft found for {doc_id}")
    authoring.discard_draft(doc_id)
    return {"discarded": True, "doc_id": doc_id}


@router.post("/editor/{doc_id}/summary/regenerate",
             summary="Regenerate draft summary deterministically")
def regen_summary(doc_id: str, _operator: str = Depends(require_operator)):
    """Re-derive summary from the current draft body_text. No LLM involved."""
    if not authoring.get_draft(doc_id):
        raise HTTPException(status_code=404,
                            detail=f"No draft found for {doc_id}")
    new_summary = authoring.regenerate_summary(doc_id)
    return {"doc_id": doc_id, "summary": new_summary}

"""app/api/routes/input_routes.py: Browser intake endpoints for Bag of Holding v2.

Phase 11 addition.

  POST /api/input/markdown  — create a Markdown note from the browser
  POST /api/input/upload    — upload one or more files
  GET  /api/input/recent    — recent browser-created/imported docs (from audit log)
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import input_surface

router = APIRouter(prefix="/api/input", tags=["input"])


class MarkdownNoteRequest(BaseModel):
    title:         str = "Untitled note"
    body:          str = ""
    topics:        list[str] = []
    target_folder: str = "notes"


@router.post("/markdown", summary="Create a Markdown note from the browser")
def create_markdown_note(req: MarkdownNoteRequest):
    """Save a browser-created Markdown note into the managed library.

    Safety guarantees:
      - Title slugified; filename sanitized
      - Path constrained to library root (no traversal)
      - File never overwrites existing (collision suffix used)
      - Status always draft; never canonical
    """
    body = req.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Body is empty. Nothing saved.")

    title = req.title.strip() or "Untitled note"

    try:
        result = input_surface.save_markdown_note(
            title=title,
            body=body,
            topics=[t.strip() for t in req.topics if t.strip()],
            target_folder=req.target_folder or "notes",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save failed: {e}")

    return {
        "ok":          True,
        "doc_id":      result["doc_id"],
        "path":        result["path"],
        "indexed":     result["indexed"],
        "lint_errors": result["lint_errors"],
    }


@router.post("/upload", summary="Upload one or more files into the managed library")
async def upload_files(
    files:         list[UploadFile],
    target_folder: str = "imports",
):
    """Upload files into the managed library.

    Accepted extensions: .md .txt .markdown .rst .csv .json .html .htm .yaml .yml
    Rejected: empty files, unsafe filenames, unsupported extensions.
    Collision: adds -2, -3 suffix instead of overwriting.
    .md/.txt files without BOH frontmatter get minimal frontmatter injected.
    """
    if not files:
        raise HTTPException(status_code=422, detail="No files provided.")

    saved    = []
    rejected = []

    for upload in files:
        try:
            content_bytes = await upload.read()
            result = input_surface.save_upload(
                filename=upload.filename or "upload",
                content_bytes=content_bytes,
                target_folder=target_folder or "imports",
            )
            if "reason" in result:
                rejected.append({"filename": upload.filename, "reason": result["reason"]})
            else:
                saved.append({
                    "filename":    result["filename"],
                    "path":        result["path"],
                    "indexed":     result["indexed"],
                    "doc_id":      result.get("doc_id"),
                    "lint_errors": result.get("lint_errors", []),
                })
        except ValueError as e:
            rejected.append({"filename": getattr(upload, "filename", "?"), "reason": str(e)})
        except Exception as e:
            rejected.append({"filename": getattr(upload, "filename", "?"),
                             "reason": f"error: {e}"})

    return {"ok": True, "saved": saved, "rejected": rejected}


@router.get("/recent", summary="Recent browser-created or imported documents")
def recent_intake(limit: int = 20):
    """Return recent browser intake events from the audit log.

    Falls back to last 20 save events from audit_log table.
    """
    try:
        from app.core.audit import get_events
        events = get_events(event_type="save", limit=limit)
        return {
            "items": [
                {
                    "event_ts":  e.get("event_ts"),
                    "doc_id":    e.get("doc_id"),
                    "actor_id":  e.get("actor_id"),
                    "detail":    e.get("detail"),
                }
                for e in events
                if e.get("actor_id") in ("browser", "human")
            ]
        }
    except Exception as e:
        return {"items": [], "error": str(e)}

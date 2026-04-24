"""app/core/ollama.py: Ollama local LLM adapter for Bag of Holding v2.

Phase 10 addition. Provides task-scoped, structured invocations against a
local Ollama endpoint. Not a freeform chat interface.

Design rules:
  - All calls are task-typed (summarize_doc, review_doc, generate_code, etc.)
  - Every invocation is recorded in llm_invocations for audit
  - Context scope (visible dirs/docs) declared per call
  - Structured JSON output requested where possible
  - Models cannot write to canon directly
  - Ollama endpoint is configurable via BOH_OLLAMA_URL env var
"""

import hashlib
import json
import os
import time
import uuid
from typing import Any, Optional
from urllib import request as urllib_request
from urllib.error import URLError

from app.db import connection as db
from app.core import audit

OLLAMA_URL    = os.environ.get("BOH_OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("BOH_OLLAMA_MODEL", "llama3.2")

TASK_TYPES = {
    "summarize_doc",
    "review_doc",
    "extract_definitions",
    "propose_metadata_patch",
    "generate_code",
    "explain_conflict",
    "query_corpus",
}

# System prompts per task type
TASK_SYSTEM_PROMPTS = {
    "summarize_doc": (
        "You are a document summarizer for a structured knowledge system. "
        "Return ONLY a JSON object: {\"summary\": \"<2-3 sentence plain-text summary>\"}. "
        "No markdown. No preamble."
    ),
    "review_doc": (
        "You are a document reviewer. Identify structural issues, missing metadata, "
        "and potential conflicts. Return ONLY JSON: "
        "{\"issues\": [...], \"suggestions\": [...], \"quality_score\": 0.0-1.0}."
    ),
    "extract_definitions": (
        "Extract all explicit definitions from the document. "
        "Return ONLY JSON: {\"definitions\": [{\"term\": \"\", \"definition\": \"\"}]}."
    ),
    "propose_metadata_patch": (
        "Propose improvements to the document frontmatter. "
        "Return ONLY JSON: {\"proposed_patch\": {\"field\": \"value\"}, \"reasoning\": \"\"}. "
        "Non-authoritative — human confirmation required."
    ),
    "generate_code": (
        "Generate Python code for the described task. "
        "Return ONLY JSON: {\"code\": \"...\", \"language\": \"python\", \"description\": \"...\"}."
    ),
    "explain_conflict": (
        "Explain the conflict between the provided documents. "
        "Return ONLY JSON: {\"explanation\": \"\", \"resolution_suggestions\": []}."
    ),
    "query_corpus": (
        "Answer the question using only the provided document excerpts. "
        "Return ONLY JSON: {\"answer\": \"\", \"confidence\": 0.0-1.0, \"sources\": []}."
    ),
}


# ── Ollama HTTP client ────────────────────────────────────────────────────────

def health_check() -> dict:
    """Test Ollama availability. Returns {available: bool, models: [...], error: ...}."""
    try:
        req = urllib_request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib_request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return {"available": True, "models": models, "url": OLLAMA_URL}
    except URLError as e:
        return {"available": False, "models": [], "url": OLLAMA_URL, "error": str(e)}
    except Exception as e:
        return {"available": False, "models": [], "url": OLLAMA_URL, "error": str(e)}


def list_models() -> list[str]:
    """Return available model names from Ollama."""
    result = health_check()
    return result.get("models", [])


def _call_ollama(model: str, system_prompt: str, user_content: str,
                 timeout: int = 60) -> tuple[str, Optional[str]]:
    """Low-level Ollama /api/chat call. Returns (response_text, error_str)."""
    payload = json.dumps({
        "model":    model,
        "stream":   False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
    }).encode("utf-8")

    try:
        req = urllib_request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            text = data.get("message", {}).get("content", "")
            return text, None
    except Exception as e:
        return "", str(e)


# ── Task invocation ───────────────────────────────────────────────────────────

def _new_invocation_id() -> str:
    return f"llm-{uuid.uuid4().hex[:12]}"


def _record_invocation(invocation_id: str, task_type: str, model: str,
                       doc_id: Optional[str], scope_json: str,
                       prompt_hash: str) -> None:
    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT INTO llm_invocations
              (invocation_id, task_type, model, provider, doc_id, scope_json,
               prompt_hash, status, started_ts)
            VALUES (?,?,?,'ollama',?,?,?,'running',?)
            """,
            (invocation_id, task_type, model, doc_id, scope_json,
             prompt_hash, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def _finish_invocation(invocation_id: str, response_text: str,
                       response_json: Optional[dict],
                       error: Optional[str]) -> None:
    status = "error" if error else "success"
    conn = db.get_conn()
    try:
        conn.execute(
            """
            UPDATE llm_invocations
            SET response_text=?, response_json=?, status=?, finished_ts=?, error=?
            WHERE invocation_id=?
            """,
            (
                response_text,
                json.dumps(response_json) if response_json else None,
                status,
                int(time.time()),
                error,
                invocation_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _build_scoped_context(scope: dict, content: str) -> str:
    """Construct the user content from declared scope only.

    scope = {
        dirs: [str]   — visible library directories (relative to BOH_LIBRARY)
        docs: [str]   — explicit doc_ids whose title+summary are visible
        allow_write_proposals: bool
    }

    Only information explicitly listed in scope is included in the prompt.
    Raw filesystem access is never used — only DB metadata for listed docs.
    If scope is empty, content is passed through unmodified.
    """
    if not scope:
        return content

    visible_docs = scope.get("docs") or []
    visible_dirs = scope.get("dirs") or []

    if not visible_docs and not visible_dirs:
        return content

    context_lines = [content, ""]

    # Append summaries of explicitly allowed docs
    if visible_docs:
        context_lines.append("=== Visible documents (scope-limited) ===")
        from app.db import connection as db
        placeholders = ",".join("?" * len(visible_docs))
        rows = db.fetchall(
            f"SELECT doc_id, title, summary, status FROM docs WHERE doc_id IN ({placeholders})",
            tuple(visible_docs),
        )
        for row in rows:
            context_lines.append(
                f"[doc_id={row['doc_id']}] {row['title'] or '(untitled)'}"
                f"{': ' + row['summary'][:200] if row.get('summary') else ''}"
            )
        context_lines.append("")

    # Append directory listing (titles only — no file content beyond scope)
    if visible_dirs:
        context_lines.append("=== Visible directories (scope-limited) ===")
        from app.db import connection as db
        for d in visible_dirs:
            rows = db.fetchall(
                "SELECT doc_id, title, path FROM docs WHERE path LIKE ?",
                (f"{d.rstrip('/')}%",),
            )
            if rows:
                context_lines.append(f"Directory: {d}")
                for row in rows[:20]:  # max 20 docs per dir to avoid token explosion
                    context_lines.append(f"  - {row['title'] or row['path']}")

    return "\n".join(context_lines)


def invoke(
    task_type: str,
    content: str,
    model: Optional[str] = None,
    doc_id: Optional[str] = None,
    scope: Optional[dict] = None,
    timeout: int = 60,
) -> dict:
    """Execute a task-scoped LLM invocation.

    Scope enforcement:
      - Context is constructed from scope.docs and scope.dirs only
      - No raw filesystem access; only DB metadata for declared docs
      - If scope is None or empty, content is passed as-is

    Args:
        task_type: one of TASK_TYPES
        content:   user-facing content (question, document text, etc.)
        model:     Ollama model name (default: BOH_OLLAMA_MODEL env var)
        doc_id:    source document ID if applicable
        scope:     {dirs: [...], docs: [...], allow_write_proposals: bool}
        timeout:   seconds before giving up

    Returns dict with:
        invocation_id, task_type, model, status,
        response_text, response_json (parsed if valid),
        non_authoritative (always True),
        error (if failed)
    """
    if task_type not in TASK_TYPES:
        return {"error": f"Unknown task_type: {task_type}. Valid: {sorted(TASK_TYPES)}"}

    model  = model or DEFAULT_MODEL
    scope  = scope or {}
    scope_json = json.dumps(scope)

    # ── Scope enforcement: build restricted context ────────────────────────────
    scoped_content = _build_scoped_context(scope, content)

    system_prompt = TASK_SYSTEM_PROMPTS[task_type]
    prompt_hash   = hashlib.sha256((system_prompt + scoped_content).encode()).hexdigest()[:32]

    invocation_id = _new_invocation_id()
    _record_invocation(invocation_id, task_type, model, doc_id, scope_json, prompt_hash)

    audit.log_event(
        event_type="llm_call",
        actor_type="model",
        actor_id=model,
        doc_id=doc_id,
        detail=json.dumps({"invocation_id": invocation_id, "task_type": task_type,
                           "scope_dirs": scope.get("dirs", []),
                           "scope_docs": scope.get("docs", [])}),
    )

    response_text, error = _call_ollama(model, system_prompt, scoped_content, timeout)

    # Attempt structured JSON parse
    response_json = None
    if response_text and not error:
        clean = response_text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        try:
            response_json = json.loads(clean)
        except json.JSONDecodeError:
            pass

    _finish_invocation(invocation_id, response_text, response_json, error)

    return {
        "invocation_id":  invocation_id,
        "task_type":      task_type,
        "model":          model,
        "doc_id":         doc_id,
        "scope_enforced": bool(scope.get("docs") or scope.get("dirs")),
        "status":         "error" if error else "success",
        "response_text":  response_text,
        "response_json":  response_json,
        "non_authoritative": True,
        "requires_explicit_confirmation": True,
        "error":          error,
    }


def get_invocation(invocation_id: str) -> dict | None:
    """Fetch a single invocation record."""
    return db.fetchone(
        "SELECT * FROM llm_invocations WHERE invocation_id = ?",
        (invocation_id,),
    )


def list_invocations(doc_id: Optional[str] = None,
                     task_type: Optional[str] = None,
                     limit: int = 20) -> list[dict]:
    """List recent LLM invocations, optionally filtered."""
    query = "SELECT invocation_id, task_type, model, doc_id, status, started_ts FROM llm_invocations WHERE 1=1"
    params: list[Any] = []
    if doc_id:
        query += " AND doc_id = ?"
        params.append(doc_id)
    if task_type:
        query += " AND task_type = ?"
        params.append(task_type)
    query += " ORDER BY started_ts DESC LIMIT ?"
    params.append(limit)
    return db.fetchall(query, tuple(params))

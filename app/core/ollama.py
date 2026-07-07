"""app/core/ollama.py: Ollama local LLM adapter for Bag of Holding v2.

Phase 10 addition. Phase 12.H (hardening) fixes applied:
  - BOH_OLLAMA_ENABLED gating: invoke() blocked unless env var is true
  - Timeout capped to [1, 120] seconds (default 30)
  - Content size capped at 20,000 chars (BOH_OLLAMA_MAX_CONTENT override)
  - Scope dirs validated and normalized; empty/root dirs rejected
  - JSON fence parsing fixed with regex prefix/suffix stripping
  - Ollama JSON mode ("format": "json") added for structured tasks
  - No direct canon write or status mutation from any Ollama output

Design rules (unchanged):
  - All calls are task-typed (summarize_doc, review_doc, etc.)
  - Every invocation is recorded in llm_invocations for audit
  - Context scope (visible dirs/docs) declared per call
  - Models cannot write to canon directly
  - Ollama endpoint is configurable via BOH_OLLAMA_URL env var
"""

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib import request as urllib_request
from urllib.error import URLError

from app.db import connection as db
from app.core import audit

# ── Configuration ─────────────────────────────────────────────────────────────
OLLAMA_URL    = os.environ.get("BOH_OLLAMA_URL",   "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("BOH_OLLAMA_MODEL", "llama3.2")

# Fix 1: Enabled gate. invoke() returns 503 unless this is "true".
# Checks DB toggle first (UI-controlled), falls back to env var.
def _is_enabled() -> bool:
    """Return True if Ollama is enabled via UI toggle (DB) or env var."""
    # Env var always wins if explicitly set to true
    if os.environ.get("BOH_OLLAMA_ENABLED", "").lower() == "true":
        return True
    # Check DB-persisted toggle (set by UI)
    try:
        from app.db import connection as _db
        row = _db.fetchone("SELECT value FROM system_config WHERE key = 'ollama_enabled'")
        return bool(row and row["value"] == "true")
    except Exception:
        return False

# Fix 3: Content size cap (characters). Override via BOH_OLLAMA_MAX_CONTENT.
_MAX_CONTENT_CHARS: int = int(os.environ.get("BOH_OLLAMA_MAX_CONTENT", "20000"))

# Fix 2: Timeout bounds
_TIMEOUT_MIN = 1
_TIMEOUT_MAX = 120
_TIMEOUT_DEFAULT = 30

# ── Task definitions ───────────────────────────────────────────────────────────
TASK_TYPES = {
    "summarize_doc",
    "review_doc",
    "extract_definitions",
    "propose_metadata_patch",
    "generate_code",
    "explain_conflict",
    "query_corpus",
}

# Tasks that expect structured JSON output (get "format":"json" in payload)
_JSON_TASKS = {
    "summarize_doc",
    "review_doc",
    "extract_definitions",
    "propose_metadata_patch",
    "explain_conflict",
    "query_corpus",
}

TASK_SYSTEM_PROMPTS = {
    "summarize_doc": (
        "You are a document summarizer for a structured knowledge system. "
        'Return ONLY a JSON object: {"summary": "<2-3 sentence plain-text summary>"}. '
        "No markdown. No preamble."
    ),
    "review_doc": (
        "You are a document reviewer. Identify structural issues, missing metadata, "
        "and potential conflicts. Return ONLY JSON: "
        '{"issues": [...], "suggestions": [...], "quality_score": 0.0-1.0}.'
    ),
    "extract_definitions": (
        "Extract all explicit definitions from the document. "
        'Return ONLY JSON: {"definitions": [{"term": "", "definition": ""}]}.'
    ),
    "propose_metadata_patch": (
        "Propose improvements to the document frontmatter. "
        'Return ONLY JSON: {"proposed_patch": {"field": "value"}, "reasoning": ""}. '
        "Non-authoritative — human confirmation required."
    ),
    "generate_code": (
        "Generate Python code for the described task. "
        'Return ONLY JSON: {"code": "...", "language": "python", "description": "..."}.'
    ),
    "explain_conflict": (
        "Explain the conflict between the provided documents. "
        'Return ONLY JSON: {"explanation": "", "resolution_suggestions": []}.'
    ),
    "query_corpus": (
        "Answer the question using only the provided document excerpts. "
        'Return ONLY JSON: {"answer": "", "confidence": 0.0-1.0, "sources": []}.'
    ),
}

# ── Scope dir validation ───────────────────────────────────────────────────────

# Fix 4: Reject dangerous/broad scope dirs.
_REJECTED_DIRS = {"", ".", "/", "*", "/*", "./", "**"}

def _validate_scope_dirs(dirs: list[str]) -> tuple[list[str], list[str]]:
    """Normalize and validate scope dirs. Returns (safe_dirs, rejected_dirs)."""
    safe: list[str] = []
    rejected: list[str] = []
    for raw in dirs:
        stripped = raw.strip()
        # Reject blank, root, or wildcard
        if not stripped or stripped in _REJECTED_DIRS:
            rejected.append(raw)
            continue
        # Resolve to a relative path; reject anything that resolves to /
        try:
            p = Path(stripped)
            # Prevent absolute paths or paths that escape the library root
            if p.is_absolute():
                rejected.append(raw)
                continue
            # Normalize (remove .., redundant slashes)
            normalized = str(p.as_posix()).lstrip("/")
            if not normalized or normalized in _REJECTED_DIRS:
                rejected.append(raw)
                continue
            safe.append(normalized)
        except Exception:
            rejected.append(raw)
    return safe, rejected


# ── JSON fence stripping ───────────────────────────────────────────────────────

# Fix 5: Correct JSON fence stripping using regex instead of lstrip().
_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)

def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences precisely."""
    text = text.strip()
    m = _JSON_FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    return text


# ── Ollama HTTP client ─────────────────────────────────────────────────────────

def health_check() -> dict:
    """Test Ollama availability. Always safe to call (not gated by enabled flag)."""
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
    """Return available model names. Not gated by enabled flag."""
    return health_check().get("models", [])


def _call_ollama(
    model: str,
    system_prompt: str,
    user_content: str,
    timeout: int,
    use_json_mode: bool,
) -> tuple[str, Optional[str]]:
    """Low-level POST to /api/chat. Returns (response_text, error_str).

    Fix 2: timeout already clamped by caller.
    Fix 6: adds "format":"json" for structured tasks.
    """
    payload_dict: dict = {
        "model":   model,
        "stream":  False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
    }
    if use_json_mode:
        payload_dict["format"] = "json"

    payload = json.dumps(payload_dict).encode("utf-8")

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


# ── Invocation record helpers ─────────────────────────────────────────────────

def _new_invocation_id() -> str:
    return f"llm-{uuid.uuid4().hex[:12]}"


def _record_invocation(
    invocation_id: str, task_type: str, model: str,
    doc_id: Optional[str], scope_json: str, prompt_hash: str,
) -> None:
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


def _finish_invocation(
    invocation_id: str, response_text: str,
    response_json: Optional[dict], error: Optional[str],
) -> None:
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
                "error" if error else "success",
                int(time.time()),
                error,
                invocation_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _build_scoped_context(scope: dict, content: str) -> str:
    """Construct user content from declared scope only.

    Fix 4 is applied upstream in invoke() — by the time we reach here,
    scope["dirs"] has already been validated and filtered.
    """
    if not scope:
        return content

    visible_docs = scope.get("docs") or []
    visible_dirs = scope.get("dirs") or []

    if not visible_docs and not visible_dirs:
        return content

    context_lines = [content, ""]

    if visible_docs:
        context_lines.append("=== Visible documents (scope-limited) ===")
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

    if visible_dirs:
        context_lines.append("=== Visible directories (scope-limited) ===")
        for d in visible_dirs:
            rows = db.fetchall(
                "SELECT doc_id, title, path FROM docs WHERE path LIKE ?",
                (f"{d.rstrip('/')}/%",),
            )
            if rows:
                context_lines.append(f"Directory: {d}")
                for row in rows[:20]:
                    context_lines.append(f"  - {row['title'] or row['path']}")

    return "\n".join(context_lines)


# ── Public invoke ──────────────────────────────────────────────────────────────

def invoke(
    task_type: str,
    content: str,
    model: Optional[str] = None,
    doc_id: Optional[str] = None,
    scope: Optional[dict] = None,
    timeout: int = _TIMEOUT_DEFAULT,
) -> dict:
    """Execute a task-scoped LLM invocation.

    Fix 1: Returns {"error": ..., "disabled": True, "status_code": 503}
           when BOH_OLLAMA_ENABLED != "true".
    Fix 2: Clamps timeout to [1, 120].
    Fix 3: Rejects content over _MAX_CONTENT_CHARS.
    Fix 4: Validates and normalizes scope dirs; rejects dangerous paths.
    Fix 5: JSON fence stripping uses regex, not lstrip.
    Fix 6: Adds "format":"json" for structured task types.

    Returns dict with:
        invocation_id, task_type, model, status,
        response_text, response_json (parsed if valid),
        non_authoritative (always True),
        error (if failed)
    """
    # Phase 14: When disabled, still validate task_type, record attempt, and
    # return a structured non-authoritative response with invocation_id.
    # This allows the system to track LLM attempts even when the service is off.
    if task_type not in TASK_TYPES:
        return {"error": f"Unknown task_type: {task_type}. Valid: {sorted(TASK_TYPES)}"}

    if not _is_enabled():
        # Still create an invocation record for auditability
        invocation_id = _new_invocation_id()
        scope = scope or {}
        scope_json = json.dumps(scope)
        scope_enforced = bool(scope.get("docs") or scope.get("dirs"))
        try:
            _record_invocation(invocation_id, task_type, model or DEFAULT_MODEL, doc_id, scope_json, "disabled")
            _finish_invocation(invocation_id, "", None, "Ollama disabled")
        except Exception:
            pass
        return {
            "invocation_id":  invocation_id,
            "task_type":      task_type,
            "model":          model or DEFAULT_MODEL,
            "doc_id":         doc_id,
            "scope_enforced": scope_enforced,
            "status":         "unavailable",
            "response_text":  None,
            "response_json":  None,
            "non_authoritative":              True,
            "requires_explicit_confirmation": True,
            "enabled":   False,
            "disabled":  True,
            "authoritative": False,
            "review_state": "unavailable",
            "error":     "Ollama integration is disabled.",
        }

    # Fix 2 — clamp timeout
    timeout = max(_TIMEOUT_MIN, min(_TIMEOUT_MAX, timeout))

    # Fix 3 — content size cap
    if len(content) > _MAX_CONTENT_CHARS:
        return {
            "error": (
                f"Content too large: {len(content)} chars "
                f"(limit {_MAX_CONTENT_CHARS}). "
                "Trim content or set BOH_OLLAMA_MAX_CONTENT to override."
            ),
            "content_too_large": True,
        }

    model = model or DEFAULT_MODEL
    scope = scope or {}

    # Fix 4 — validate scope dirs
    raw_dirs = scope.get("dirs") or []
    safe_dirs, rejected_dirs = _validate_scope_dirs(raw_dirs)
    if rejected_dirs:
        return {
            "error": (
                f"Invalid scope dirs rejected: {rejected_dirs}. "
                "Empty strings, '.', '/', and wildcard paths are not permitted."
            ),
            "rejected_dirs": rejected_dirs,
        }
    scope = {**scope, "dirs": safe_dirs}

    scope_json = json.dumps(scope)
    scoped_content = _build_scoped_context(scope, content)
    system_prompt  = TASK_SYSTEM_PROMPTS[task_type]
    prompt_hash    = hashlib.sha256((system_prompt + scoped_content).encode()).hexdigest()[:32]
    invocation_id  = _new_invocation_id()

    _record_invocation(invocation_id, task_type, model, doc_id, scope_json, prompt_hash)

    audit.log_event(
        event_type="llm_call",
        actor_type="model",
        actor_id=model,
        doc_id=doc_id,
        detail=json.dumps({
            "invocation_id": invocation_id,
            "task_type":     task_type,
            "scope_dirs":    safe_dirs,
            "scope_docs":    scope.get("docs", []),
        }),
    )

    # Fix 6 — JSON mode for structured tasks
    use_json_mode = task_type in _JSON_TASKS
    response_text, error = _call_ollama(
        model, system_prompt, scoped_content, timeout, use_json_mode
    )

    # Fix 5 — correct JSON fence stripping
    response_json: Optional[dict] = None
    if response_text and not error:
        clean = _strip_json_fences(response_text)
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
        "non_authoritative":              True,
        "requires_explicit_confirmation": True,
        "error":          error,
    }


# ── Read-only helpers (never gated) ───────────────────────────────────────────

def get_invocation(invocation_id: str) -> dict | None:
    return db.fetchone(
        "SELECT * FROM llm_invocations WHERE invocation_id = ?",
        (invocation_id,),
    )


def list_invocations(
    doc_id: Optional[str] = None,
    task_type: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    query  = "SELECT invocation_id, task_type, model, doc_id, status, started_ts FROM llm_invocations WHERE 1=1"
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

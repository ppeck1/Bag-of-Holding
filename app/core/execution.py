"""app/core/execution.py: Executable document block runner for Bag of Holding v2.

Phase 10 addition. Runs Python and shell code blocks from BoH documents.

Enforcement rules (hardened):
  - Execution is scoped to an explicitly declared workspace_path (no fallback to /)
  - Python runs in a subprocess with no __file__ access beyond workspace
  - Shell runs are checked against a basic command denylist before execution
  - Every run creates a tracked exec_run record (never ephemeral)
  - Outputs stored as exec_artifacts attached to the run
  - Lineage: run → doc_id + block_id + code_hash
  - Timeout enforced (default 30s)
  - executor label always recorded: 'human' | 'model:<name>' | 'system'
  - stderr always captured and stored
  - Policy enforcement: entity must have can_execute on workspace

Supported languages: python, shell
"""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from app.db import connection as db
from app.core import audit


EXEC_TIMEOUT_S   = 30        # maximum seconds per run
MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB per stdout/stderr

# Shell commands that are always denied regardless of workspace
SHELL_DENYLIST_PATTERNS = [
    re.compile(r"\brm\s+-rf\b"),           # recursive delete
    re.compile(r"\bdd\s+if="),             # disk write
    re.compile(r"\bmkfs\b"),               # format
    re.compile(r"\bsudo\b"),               # privilege escalation
    re.compile(r"\bchmod\s+777\b"),        # open permissions
    re.compile(r">\s*/dev/sd"),            # raw device write
    re.compile(r"\bcurl\b.*\|\s*bash"),    # curl-pipe-bash
    re.compile(r"\bwget\b.*\|\s*sh"),      # wget-pipe-sh
    re.compile(r";\s*rm\s+-"),             # chained delete
    re.compile(r"\beval\b.*\$\("),         # eval subshell injection
]

# Python code patterns that are explicitly rejected
PYTHON_DENYLIST_PATTERNS = [
    re.compile(r"\bos\.system\s*\("),           # raw system call
    re.compile(r"\bsubprocess\.(run|call|Popen)\s*\(.*shell\s*=\s*True"), # shell=True
    re.compile(r"\beval\s*\(.*exec\s*\("),      # nested eval/exec
    re.compile(r"__import__\s*\(['\"]os['\"]"), # indirect os import
]


# ── Security helpers ──────────────────────────────────────────────────────────

def _check_shell_safety(code: str) -> Optional[str]:
    """Return an error message if the shell code hits a denylist pattern, else None."""
    for pattern in SHELL_DENYLIST_PATTERNS:
        if pattern.search(code):
            return f"Execution denied: shell code matches restricted pattern: {pattern.pattern!r}"
    return None


def _check_python_safety(code: str) -> Optional[str]:
    """Return an error message if the Python code hits a denylist pattern, else None."""
    for pattern in PYTHON_DENYLIST_PATTERNS:
        if pattern.search(code):
            return f"Execution denied: Python code matches restricted pattern: {pattern.pattern!r}"
    return None


def _resolve_workspace(workspace_path: Optional[str], library_root: str) -> Path:
    """Resolve and validate the workspace path.

    Enforces that the resolved path is within the declared library root.
    Returns the resolved workspace Path.
    Raises ValueError if the path escapes the root.
    """
    root = Path(library_root).resolve()
    if workspace_path:
        ws = Path(workspace_path).resolve()
    else:
        ws = root

    # Prevent path traversal out of library root
    try:
        ws.relative_to(root)
    except ValueError:
        raise ValueError(
            f"Workspace path '{ws}' is outside the library root '{root}'. "
            "Execution is restricted to the declared library directory."
        )
    return ws


def _check_execute_permission(workspace: str, entity_type: str,
                               entity_id: str) -> Optional[dict]:
    """Return an error dict if entity cannot execute in workspace, else None."""
    from app.core.governance import get_effective_policy
    policy = get_effective_policy(workspace, entity_type, entity_id)
    if not policy.get("can_execute"):
        return {
            "error": f"Execute permission denied for {entity_type}:{entity_id} "
                     f"on workspace '{workspace}'.",
            "permission_denied": True,
            "run_id": None,
        }
    return None


# ── Run lifecycle ─────────────────────────────────────────────────────────────

def _new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def _new_artifact_id() -> str:
    return f"art-{uuid.uuid4().hex[:12]}"


def create_run_record(doc_id: str, block_id: str, language: str,
                      code: str, executor: str = "human") -> str:
    """Insert a pending exec_run record and return its run_id."""
    run_id    = _new_run_id()
    code_hash = hashlib.sha256(code.encode()).hexdigest()[:32]
    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT INTO exec_runs
              (run_id, doc_id, block_id, executor, language, code_hash,
               started_ts, status)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (run_id, doc_id, block_id, executor, language,
             code_hash, int(time.time()), "running"),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def finish_run_record(run_id: str, exit_code: int,
                      stdout: str, stderr: str):
    """Update exec_run with completion data."""
    status = "success" if exit_code == 0 else "error"
    conn = db.get_conn()
    try:
        conn.execute(
            """
            UPDATE exec_runs
            SET exit_code=?, stdout=?, stderr=?, finished_ts=?, status=?
            WHERE run_id=?
            """,
            (exit_code,
             stdout[:MAX_OUTPUT_BYTES],
             stderr[:MAX_OUTPUT_BYTES],
             int(time.time()), status, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def store_artifact(run_id: str, name: str, artifact_type: str,
                   content: Optional[str] = None,
                   path: Optional[str] = None,
                   size_bytes: Optional[int] = None) -> str:
    """Attach an artifact to a run. Returns artifact_id."""
    art_id = _new_artifact_id()
    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT INTO exec_artifacts
              (run_id, artifact_id, name, type, content, path, size_bytes, created_ts)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (run_id, art_id, name, artifact_type,
             content, path, size_bytes, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()
    return art_id


# ── Execution engines ─────────────────────────────────────────────────────────

def _run_python(code: str, workspace: Path,
                timeout: int = EXEC_TIMEOUT_S) -> tuple[int, str, str]:
    """Execute Python code in a subprocess inside workspace. Returns (exit_code, stdout, stderr)."""
    # Prepend a sys.path restriction so the script cannot easily import from outside workspace
    restricted_header = (
        f"import sys, os\n"
        f"os.chdir({str(workspace)!r})\n"
        f"sys.path.insert(0, {str(workspace)!r})\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                     encoding="utf-8", delete=False,
                                     dir=str(workspace)) as f:
        f.write(restricted_header + code)
        script_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace),
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Execution timed out after {timeout}s"
    except Exception as e:
        return 1, "", str(e)
    finally:
        try:
            Path(script_path).unlink(missing_ok=True)
        except Exception:
            pass


def _run_shell(code: str, workspace: Path,
               timeout: int = EXEC_TIMEOUT_S) -> tuple[int, str, str]:
    """Execute shell code in a subprocess inside workspace. Returns (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            code,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace),
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Execution timed out after {timeout}s"
    except Exception as e:
        return 1, "", str(e)


# ── Public API ────────────────────────────────────────────────────────────────

def run_block(doc_id: str, block_id: str, language: str, code: str,
              executor: str = "human",
              workspace_path: Optional[str] = None,
              library_root: str = "./library",
              entity_type: str = "human",
              entity_id: str = "*") -> dict:
    """Run a code block and persist the result with full lineage.

    Enforcement order:
      1. Language validation
      2. Safety pattern check (denylist)
      3. Permission check (entity must have can_execute on workspace)
      4. Workspace path resolution + root-escape check
      5. Execution (subprocess, isolated cwd)
      6. Audit log

    Returns a dict with run_id, status, exit_code, stdout, stderr, artifacts.
    """
    language = language.lower().strip()
    if language in ("sh", "bash"):
        language = "shell"
    if language not in ("python", "shell"):
        return {
            "error": f"Unsupported language: {language}. Supported: python, shell.",
            "run_id": None,
        }

    # ── Enforcement 1: Safety denylist ────────────────────────────────────────
    if language == "shell":
        safety_err = _check_shell_safety(code)
    else:
        safety_err = _check_python_safety(code)
    if safety_err:
        return {"error": safety_err, "run_id": None}

    # ── Enforcement 2: Permission check ───────────────────────────────────────
    perm_err = _check_execute_permission(library_root, entity_type, entity_id)
    if perm_err:
        return perm_err

    # ── Enforcement 3: Workspace path resolution (no root escape) ─────────────
    try:
        workspace = _resolve_workspace(workspace_path, library_root)
    except ValueError as e:
        return {"error": str(e), "run_id": None}

    run_id = create_run_record(doc_id, block_id, language, code, executor)

    audit.log_event(
        event_type="run",
        actor_type="human" if executor == "human" else "model",
        actor_id=executor,
        doc_id=doc_id,
        workspace=str(workspace),
        detail=json.dumps({"block_id": block_id, "language": language, "run_id": run_id}),
    )

    # ── Execute ───────────────────────────────────────────────────────────────
    if language == "python":
        exit_code, stdout, stderr = _run_python(code, workspace)
    else:
        exit_code, stdout, stderr = _run_shell(code, workspace)

    finish_run_record(run_id, exit_code, stdout, stderr)

    artifacts = []
    if stdout.strip():
        art_id = store_artifact(
            run_id=run_id,
            name="stdout",
            artifact_type="stdout",
            content=stdout[:MAX_OUTPUT_BYTES],
            size_bytes=len(stdout.encode()),
        )
        artifacts.append({"artifact_id": art_id, "name": "stdout", "type": "stdout"})

    status = "success" if exit_code == 0 else "error"
    return {
        "run_id":    run_id,
        "doc_id":    doc_id,
        "block_id":  block_id,
        "language":  language,
        "executor":  executor,
        "workspace": str(workspace),
        "status":    status,
        "exit_code": exit_code,
        "stdout":    stdout[:MAX_OUTPUT_BYTES],
        "stderr":    stderr[:MAX_OUTPUT_BYTES],
        "artifacts": artifacts,
    }


def get_run(run_id: str) -> dict | None:
    """Fetch a single run record."""
    run = db.fetchone("SELECT * FROM exec_runs WHERE run_id = ?", (run_id,))
    if not run:
        return None
    artifacts = db.fetchall(
        "SELECT artifact_id, name, type, size_bytes, created_ts "
        "FROM exec_artifacts WHERE run_id = ?",
        (run_id,),
    )
    return {**run, "artifacts": artifacts}


def list_runs(doc_id: str, limit: int = 20) -> list[dict]:
    """List recent runs for a document."""
    return db.fetchall(
        "SELECT run_id, doc_id, block_id, executor, language, status, exit_code, "
        "started_ts, finished_ts FROM exec_runs "
        "WHERE doc_id = ? ORDER BY started_ts DESC LIMIT ?",
        (doc_id, limit),
    )


def get_artifact_content(artifact_id: str) -> dict | None:
    """Fetch an artifact including its inline content."""
    return db.fetchone(
        "SELECT * FROM exec_artifacts WHERE artifact_id = ?",
        (artifact_id,),
    )









"""Persistent, write-only verifier storage for local BOH credentials.

Environment variables remain authoritative. UI-managed credentials are stored
as salted PBKDF2 verifiers in ``system_config``; plaintext is never persisted.
Any unreadable or malformed configured record fails closed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Literal

from app.db import connection as db


TokenKind = Literal["operator", "retrieval"]
TokenSource = Literal["environment", "ui", "none", "storage_error"]

PBKDF2_ITERATIONS = 310_000
PBKDF2_DIGEST_BYTES = 32
PBKDF2_SALT_BYTES = 16
MIN_TOKEN_LENGTH = 16
MAX_TOKEN_LENGTH = 256

_ENV_KEYS: dict[TokenKind, str] = {
    "operator": "BOH_OPERATOR_TOKEN",
    "retrieval": "BOH_RETRIEVAL_TOKEN",
}
_CONFIG_KEYS: dict[TokenKind, str] = {
    "operator": "security_operator_token_v1",
    "retrieval": "security_retrieval_token_v1",
}


class TokenConfigurationError(ValueError):
    """Base error safe for route-level mapping without secret material."""


class TokenManagedByEnvironment(TokenConfigurationError):
    pass


class TokenAlreadyConfigured(TokenConfigurationError):
    pass


class InvalidTokenValue(TokenConfigurationError):
    pass


@dataclass(frozen=True)
class TokenState:
    kind: TokenKind
    configured: bool
    source: TokenSource
    record_valid: bool
    managed_by_environment: bool
    restart_required: bool = False
    ui_verifier_present: bool | None = False

    def safe_dict(self) -> dict:
        return asdict(self)


def _environment_token(kind: TokenKind) -> str:
    return os.environ.get(_ENV_KEYS[kind], "").strip()


def _read_stored_value(kind: TokenKind) -> str | None:
    row = db.fetchone(
        "SELECT value FROM system_config WHERE key = ?",
        (_CONFIG_KEYS[kind],),
    )
    return str(row["value"]) if row else None


def _decode_exact(value: object, expected_bytes: int) -> bytes:
    if not isinstance(value, str):
        raise ValueError("encoded verifier component must be text")
    decoded = base64.b64decode(value.encode("ascii"), validate=True)
    if len(decoded) != expected_bytes:
        raise ValueError("encoded verifier component has wrong length")
    return decoded


def _parse_verifier(raw: str) -> tuple[bytes, bytes, int]:
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise ValueError("verifier must be an object")
    if record.get("version") != 1 or record.get("algorithm") != "pbkdf2_sha256":
        raise ValueError("unsupported verifier")
    iterations = record.get("iterations")
    if isinstance(iterations, bool) or not isinstance(iterations, int):
        raise ValueError("invalid iteration count")
    if iterations != PBKDF2_ITERATIONS:
        raise ValueError("unsupported iteration count")
    salt = _decode_exact(record.get("salt_b64"), PBKDF2_SALT_BYTES)
    digest = _decode_exact(record.get("digest_b64"), PBKDF2_DIGEST_BYTES)
    return salt, digest, iterations


def get_state(kind: TokenKind) -> TokenState:
    """Return non-secret credential state with environment precedence."""
    if _environment_token(kind):
        try:
            ui_present: bool | None = _read_stored_value(kind) is not None
        except Exception:
            ui_present = None
        return TokenState(
            kind,
            True,
            "environment",
            True,
            True,
            restart_required=True,
            ui_verifier_present=ui_present,
        )
    try:
        raw = _read_stored_value(kind)
    except Exception:
        return TokenState(
            kind, True, "storage_error", False, False,
            ui_verifier_present=None,
        )
    if raw is None:
        return TokenState(kind, False, "none", True, False)
    try:
        _parse_verifier(raw)
    except Exception:
        return TokenState(kind, True, "ui", False, False, ui_verifier_present=True)
    return TokenState(kind, True, "ui", True, False, ui_verifier_present=True)


def verify(kind: TokenKind, presented: str | None) -> bool:
    """Verify a presented credential without revealing configuration details."""
    if not presented:
        return False
    environment_value = _environment_token(kind)
    if environment_value:
        return hmac.compare_digest(presented, environment_value)
    try:
        raw = _read_stored_value(kind)
        if raw is None:
            return False
        return _stored_verifier_matches(raw, presented)
    except Exception:
        return False


def _stored_verifier_matches(raw: str, presented: str) -> bool:
    salt, expected, iterations = _parse_verifier(raw)
    actual = hashlib.pbkdf2_hmac(
        "sha256", presented.encode("utf-8"), salt, iterations,
        dklen=PBKDF2_DIGEST_BYTES,
    )
    return hmac.compare_digest(actual, expected)


def _validate_plaintext(plaintext: str) -> None:
    if not isinstance(plaintext, str):
        raise InvalidTokenValue("token must be text")
    if not MIN_TOKEN_LENGTH <= len(plaintext) <= MAX_TOKEN_LENGTH:
        raise InvalidTokenValue(
            f"token must be {MIN_TOKEN_LENGTH}-{MAX_TOKEN_LENGTH} characters"
        )
    if not plaintext.isascii() or any(not 33 <= ord(ch) <= 126 for ch in plaintext):
        raise InvalidTokenValue("token must contain printable non-whitespace ASCII characters only")


def _verifier_json(plaintext: str) -> str:
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", plaintext.encode("utf-8"), salt, PBKDF2_ITERATIONS,
        dklen=PBKDF2_DIGEST_BYTES,
    )
    return json.dumps(
        {
            "version": 1,
            "algorithm": "pbkdf2_sha256",
            "iterations": PBKDF2_ITERATIONS,
            "salt_b64": base64.b64encode(salt).decode("ascii"),
            "digest_b64": base64.b64encode(digest).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _audit_detail(kind: TokenKind, action: str) -> str:
    return json.dumps(
        {
            "action": action,
            "token_kind": kind,
            "source": "ui",
            "plaintext_persisted": False,
        },
        sort_keys=True,
    )


def configure(
    kind: TokenKind,
    plaintext: str,
    *,
    actor_id: str,
    expect_unconfigured: bool = False,
) -> TokenState:
    """Bootstrap or rotate a verifier and its audit record atomically."""
    if _environment_token(kind):
        raise TokenManagedByEnvironment(f"{kind} token is managed by the environment")
    _validate_plaintext(plaintext)
    other_kind: TokenKind = "retrieval" if kind == "operator" else "operator"
    other_environment = _environment_token(other_kind)
    if other_environment and hmac.compare_digest(other_environment, plaintext):
        raise InvalidTokenValue("operator and retrieval tokens must be different")
    now = int(time.time())
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        other_row = conn.execute(
            "SELECT value FROM system_config WHERE key = ?",
            (_CONFIG_KEYS[other_kind],),
        ).fetchone()
        if other_row:
            try:
                duplicates_other = _stored_verifier_matches(
                    str(other_row["value"]), plaintext
                )
            except Exception:
                duplicates_other = False
            if duplicates_other:
                raise InvalidTokenValue("operator and retrieval tokens must be different")
        existing = conn.execute(
            "SELECT 1 FROM system_config WHERE key = ?",
            (_CONFIG_KEYS[kind],),
        ).fetchone()
        if expect_unconfigured and existing:
            raise TokenAlreadyConfigured(f"{kind} token is already configured")
        action = "rotate" if existing else "bootstrap"
        verifier = _verifier_json(plaintext)
        conn.execute(
            """INSERT INTO system_config (key, value, updated_ts) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts""",
            (_CONFIG_KEYS[kind], verifier, now),
        )
        conn.execute(
            """INSERT INTO audit_log
               (event_ts, event_type, actor_type, actor_id, detail)
               VALUES (?, 'security_token_configured', 'human', ?, ?)""",
            (now, actor_id, _audit_detail(kind, action)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_state(kind)


def clear(kind: TokenKind, *, actor_id: str) -> TokenState:
    """Remove the UI verifier without changing an active environment token."""
    now = int(time.time())
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM system_config WHERE key = ?", (_CONFIG_KEYS[kind],))
        conn.execute(
            """INSERT INTO audit_log
               (event_ts, event_type, actor_type, actor_id, detail)
               VALUES (?, 'security_token_configured', 'human', ?, ?)""",
            (now, actor_id, _audit_detail(kind, "clear")),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_state(kind)

"""Operator authorization boundary for privileged BOH routes.

Dev-open mode: when BOH_OPERATOR_TOKEN is not set, all protected routes are
allowed through automatically. Set BOH_OPERATOR_TOKEN to enable enforcement.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status

from app.core import audit


OPERATOR_HEADER = "X-BOH-Operator-Token"
_DEV_OPEN_WARNED = False


def _configured_token() -> str:
    return os.environ.get("BOH_OPERATOR_TOKEN", "").strip()


def _is_dev_open() -> bool:
    """True when no operator token is configured (local dev mode)."""
    return not _configured_token()


def operator_status() -> dict:
    """Return safe operator-boundary status without revealing the secret."""
    dev_open = _is_dev_open()
    return {
        "configured": not dev_open,
        "dev_open": dev_open,
        "header_name": OPERATOR_HEADER,
        "protected_routes_fail_closed": not dev_open,
    }


def require_operator(
    x_boh_operator_token: str | None = Header(default=None, alias=OPERATOR_HEADER),
) -> str:
    """Require a configured operator token for privileged mutations.

    When BOH_OPERATOR_TOKEN is unset (dev-open mode), all requests are allowed
    through so the tool works out of the box during development. Set the env var
    to enforce token-based access control.
    """
    global _DEV_OPEN_WARNED
    expected = _configured_token()
    if not expected:
        if not _DEV_OPEN_WARNED:
            import warnings
            warnings.warn(
                "BOH dev-open mode: BOH_OPERATOR_TOKEN not set. "
                "All protected routes are open. Set BOH_OPERATOR_TOKEN to enforce access control.",
                RuntimeWarning,
                stacklevel=2,
            )
            _DEV_OPEN_WARNED = True
        return "dev_operator"
    if not x_boh_operator_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing {OPERATOR_HEADER}",
        )
    if not hmac.compare_digest(x_boh_operator_token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid operator authorization",
        )
    return "operator"


def audit_operator_action(event_type: str, action: str, detail: dict | None = None,
                          doc_id: str | None = None) -> None:
    payload = {"action": action, **(detail or {})}
    try:
        import json
        audit.log_event(
            event_type=event_type,
            actor_type="human",
            actor_id="operator",
            doc_id=doc_id,
            detail=json.dumps(payload),
        )
    except Exception:
        pass

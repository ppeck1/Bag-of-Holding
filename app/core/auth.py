"""Operator authorization boundary for privileged BOH routes.

Dev-open mode: when neither an environment token nor a UI-managed verifier is
configured, protected routes are allowed through for local development.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core import audit
from app.core import token_config


OPERATOR_HEADER = "X-BOH-Operator-Token"
_DEV_OPEN_WARNED = False


def _is_dev_open() -> bool:
    """True only when no operator credential source is configured."""
    return not token_config.get_state("operator").configured


def operator_status() -> dict:
    """Return safe operator-boundary status without revealing the secret."""
    state = token_config.get_state("operator")
    dev_open = not state.configured
    return {
        "configured": state.configured,
        "dev_open": dev_open,
        "header_name": OPERATOR_HEADER,
        "protected_routes_fail_closed": not dev_open,
        "source": state.source,
        "record_valid": state.record_valid,
        "managed_by_environment": state.managed_by_environment,
        "restart_required": state.restart_required,
    }


def require_operator(
    x_boh_operator_token: str | None = Header(default=None, alias=OPERATOR_HEADER),
) -> str:
    """Require a configured operator token for privileged mutations.

    When no environment token or UI verifier exists (dev-open mode), requests
    are allowed through so the local tool works out of the box.
    """
    global _DEV_OPEN_WARNED
    state = token_config.get_state("operator")
    if not state.configured:
        if not _DEV_OPEN_WARNED:
            import warnings
            warnings.warn(
                "BOH dev-open mode: no operator token is configured. "
                "All protected routes are open. Configure one in Settings or the environment.",
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
    if not token_config.verify("operator", x_boh_operator_token):
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

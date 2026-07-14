"""Local-only settings routes for write-only BOH credential management."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr

from app.core.auth import require_operator
from app.core import audit, mcp_connector, token_config


router = APIRouter(prefix="/api/security", tags=["security"])
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class TokenConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr


class McpConnectorConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    tunnel_id: str
    oauth_issuer: str = ""
    scope: str = mcp_connector.DEFAULT_SCOPE
    port: int = mcp_connector.DEFAULT_PORT
    auth_mode: str = mcp_connector.DEFAULT_AUTH_MODE


class McpRuntimeKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_key: SecretStr


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.casefold() == "localhost"
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback


def _port(scheme: str, explicit: int | None) -> int | None:
    if explicit is not None:
        return explicit
    return 443 if scheme == "https" else 80 if scheme == "http" else None


def require_local_same_origin(request: Request) -> None:
    """Require a loopback peer and reject cross-origin browser mutations."""
    if not request.client or not _is_loopback(request.client.host):
        raise HTTPException(status_code=403, detail="security settings are local-only")

    # Never use a caller-controlled Host value as an authority boundary. Both
    # the socket peer and the requested host must resolve to a loopback name.
    if not _is_loopback(request.url.hostname):
        raise HTTPException(status_code=403, detail="security settings require a loopback host")

    origin = request.headers.get("origin")
    if origin is None:
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            raise HTTPException(status_code=403, detail="security mutations require same-origin proof")
        return
    try:
        parsed = urlsplit(origin)
        request_host = request.url.hostname
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and _is_loopback(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.scheme.casefold() == request.url.scheme.casefold()
            and parsed.hostname.casefold() == (request_host or "").casefold()
            and _port(parsed.scheme, parsed.port) == _port(request.url.scheme, request.url.port)
        )
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(status_code=403, detail="cross-origin security mutation rejected")


def _safe_state() -> dict:
    return {
        "operator": token_config.get_state("operator").safe_dict(),
        "retrieval": token_config.get_state("retrieval").safe_dict(),
        "plaintext_persisted": False,
    }


def _map_configuration_error(exc: Exception) -> None:
    if isinstance(exc, token_config.TokenManagedByEnvironment):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, token_config.TokenAlreadyConfigured):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, token_config.InvalidTokenValue):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="credential configuration failed") from exc


def _require_configured_operator() -> None:
    state = token_config.get_state("operator")
    if not state.configured or not state.record_valid:
        raise HTTPException(
            status_code=409,
            detail="configure a valid operator token before managing retrieval access",
        )


@router.get("/tokens", summary="Safe server credential status")
def token_status():
    return _safe_state()


@router.post("/tokens/operator", summary="Bootstrap or rotate operator verifier")
def configure_operator_token(
    payload: TokenConfigurationRequest,
    _local: None = Depends(require_local_same_origin),
    actor_id: str = Depends(require_operator),
):
    before = token_config.get_state("operator")
    try:
        state = token_config.configure(
            "operator",
            payload.token.get_secret_value(),
            actor_id=actor_id,
            expect_unconfigured=not before.configured,
        )
    except Exception as exc:
        _map_configuration_error(exc)
    return {"ok": True, "token": state.safe_dict(), "plaintext_persisted": False}


@router.delete("/tokens/operator", summary="Clear UI-managed operator verifier")
def clear_operator_token(
    _local: None = Depends(require_local_same_origin),
    actor_id: str = Depends(require_operator),
):
    try:
        state = token_config.clear("operator", actor_id=actor_id)
    except Exception as exc:
        _map_configuration_error(exc)
    return {"ok": True, "token": state.safe_dict(), "plaintext_persisted": False}


@router.post("/tokens/retrieval", summary="Set or rotate retrieval verifier")
def configure_retrieval_token(
    payload: TokenConfigurationRequest,
    _local: None = Depends(require_local_same_origin),
    actor_id: str = Depends(require_operator),
):
    _require_configured_operator()
    try:
        state = token_config.configure(
            "retrieval", payload.token.get_secret_value(), actor_id=actor_id
        )
    except Exception as exc:
        _map_configuration_error(exc)
    return {"ok": True, "token": state.safe_dict(), "plaintext_persisted": False}


@router.delete("/tokens/retrieval", summary="Clear UI-managed retrieval verifier")
def clear_retrieval_token(
    _local: None = Depends(require_local_same_origin),
    actor_id: str = Depends(require_operator),
):
    _require_configured_operator()
    try:
        state = token_config.clear("retrieval", actor_id=actor_id)
    except Exception as exc:
        _map_configuration_error(exc)
    return {"ok": True, "token": state.safe_dict(), "plaintext_persisted": False}


def _connector_response() -> dict:
    status_payload = mcp_connector.safe_status(PROJECT_ROOT)
    try:
        config = mcp_connector.load_config(PROJECT_ROOT)
    except mcp_connector.ConnectorConfigError:
        config = None
    return {
        "status": status_payload,
        "config": config.safe_dict() if config else None,
        "runtime_key_value_returned": False,
    }


def _audit_mcp_change(actor_id: str, action: str, detail: dict | None = None) -> bool:
    """Best-effort cross-store audit; callers report whether it was recorded."""
    try:
        audit.log_event(
            event_type="mcp_connector_configured",
            actor_type="human",
            actor_id=actor_id,
            detail=json.dumps(
                {
                    "action": action,
                    "source": "local_settings",
                    "secret_value_recorded": False,
                    **(detail or {}),
                },
                sort_keys=True,
            ),
        )
        return True
    except Exception:
        # File configuration and SQLite cannot share a transaction. Preserve
        # the successful file mutation and report the audit result truthfully.
        return False


@router.get("/mcp-connector", summary="Safe local MCP connector status")
def get_mcp_connector(
    _local: None = Depends(require_local_same_origin),
    _operator: str = Depends(require_operator),
):
    return _connector_response()


@router.post("/mcp-connector/config", summary="Save opt-in MCP startup configuration")
def configure_mcp_connector(
    payload: McpConnectorConfigurationRequest,
    _local: None = Depends(require_local_same_origin),
    actor_id: str = Depends(require_operator),
):
    _require_configured_operator()
    try:
        config = mcp_connector.parse_config(payload.model_dump())
        mcp_connector.save_config(PROJECT_ROOT, config)
        audit_recorded = _audit_mcp_change(
            actor_id,
            "configure",
            {"enabled": config.enabled, "scope": config.scope, "port": config.port},
        )
    except mcp_connector.ConnectorConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="MCP connector configuration failed") from exc
    response = _connector_response()
    response.update({"ok": True, "restart_required": True, "audit_recorded": audit_recorded})
    return response


@router.delete("/mcp-connector/config", summary="Disable MCP startup configuration")
def disable_mcp_connector(
    _local: None = Depends(require_local_same_origin),
    actor_id: str = Depends(require_operator),
):
    _require_configured_operator()
    try:
        mcp_connector.disable_config(PROJECT_ROOT)
        audit_recorded = _audit_mcp_change(actor_id, "disable", {"enabled": False})
    except mcp_connector.ConnectorConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="MCP connector configuration failed") from exc
    response = _connector_response()
    response.update({"ok": True, "restart_required": True, "audit_recorded": audit_recorded})
    return response


@router.post("/mcp-connector/runtime-key", summary="Write the local tunnel runtime key")
def configure_mcp_runtime_key(
    payload: McpRuntimeKeyRequest,
    _local: None = Depends(require_local_same_origin),
    actor_id: str = Depends(require_operator),
):
    _require_configured_operator()
    try:
        mcp_connector.write_runtime_key(
            PROJECT_ROOT, payload.runtime_key.get_secret_value()
        )
        audit_recorded = _audit_mcp_change(actor_id, "runtime_key_write")
    except mcp_connector.ConnectorConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="MCP runtime key write failed") from exc
    return {
        "ok": True,
        "runtime_key_configured": True,
        "runtime_key_value_returned": False,
        "restart_required": True,
        "audit_recorded": audit_recorded,
    }

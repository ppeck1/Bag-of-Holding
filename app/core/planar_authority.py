"""Fail-closed authority decisions for Planar Storage cards."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass
class Decision:
    allowed: bool
    reason: str
    required_action: str | None
    visible_message: str

    def to_dict(self) -> dict:
        return asdict(self)


def _card_dict(card: Any) -> dict:
    if hasattr(card, "to_dict"):
        return card.to_dict()
    return dict(card or {})


def _payload(card: dict) -> dict:
    return card.get("payload") or {}


def _is_expired(card: dict) -> bool:
    valid_until = card.get("valid_until")
    if not valid_until:
        return False
    try:
        return datetime.fromisoformat(str(valid_until).replace("Z", "+00:00")).timestamp() < time.time()
    except Exception:
        return False


def _confidence(card: dict) -> float:
    payload = _payload(card)
    for key in ("confidence", "epistemic_c"):
        if payload.get(key) is not None:
            return float(payload[key])
    return 0.5


def _is_llm(actor: str | dict | None) -> bool:
    if isinstance(actor, dict):
        actor_type = str(actor.get("actor_type") or actor.get("type") or "").lower()
        actor_id = str(actor.get("actor_id") or actor.get("id") or "").lower()
    else:
        actor_type = ""
        actor_id = str(actor or "").lower()
    return actor_type in {"llm", "model"} or actor_id.startswith(("llm", "ollama", "model"))


def _deny(reason: str, required_action: str | None, message: str) -> Decision:
    return Decision(False, reason, required_action, message)


def _allow(reason: str = "allowed") -> Decision:
    return Decision(True, reason, None, "Allowed by current Planar Storage policy.")


def can_use(actor: str | dict | None, card: Any, operation: str, mode: str) -> Decision:
    """Evaluate whether a card may be used in a retrieval or evidence mode."""
    c = _card_dict(card)
    plane = str(c.get("plane") or "").lower()
    payload = _payload(c)
    mode_key = str(mode or "").lower().replace(" ", "_").replace("-", "_")

    if payload.get("state") in {"deprecated", "blocked"}:
        return _deny("card_not_active", "review_card", "This card is blocked or deprecated.")
    if _is_expired(c):
        return _deny("card_expired", "refresh_or_review", "This card is expired and cannot be used without review.")

    if mode_key in {"strict_answer", "strict"}:
        if plane == "subjective":
            return _deny("subjective_excluded", "use_exploration_mode", "Subjective cards are excluded from strict answers.")
        if payload.get("non_authoritative"):
            return _deny("non_authoritative_excluded", "request_certificate", "Non-authoritative material cannot be used as strict answer context.")
        if _confidence(c) < 0.5:
            return _deny("low_confidence", "review_card", "Low-confidence cards are excluded from strict answers.")

    if operation in {"promote", "approve_certificate"}:
        return _deny("wrong_evaluator", "use_can_promote", "Promotion requires the promotion authority evaluator.")

    return _allow()


def can_promote(actor: str | dict | None, card: Any, target_plane: str,
                certificate: dict | None = None) -> Decision:
    """Fail-closed promotion evaluator."""
    c = _card_dict(card)
    source_plane = str(c.get("plane") or "").lower()
    target = str(target_plane or "").lower()

    if _is_llm(actor):
        return _deny("llm_cannot_promote", "human_review", "LLM actors may propose, but cannot promote cards.")
    if target == "canonical" and source_plane != "canonical":
        if not certificate:
            return _deny(
                "certificate_required",
                "request_certificate",
                "This card cannot be promoted to canon without an approved certificate.",
            )
        if certificate.get("status") != "approved":
            return _deny("certificate_not_approved", "approve_certificate", "The supplied certificate is not approved.")
        cert_card = certificate.get("card_id") or certificate.get("node_id")
        if cert_card and cert_card not in {c.get("id"), c.get("doc_id")}:
            return _deny("wrong_card_certificate", "request_certificate", "The certificate does not match this card.")
    return _allow("certificate_satisfied")


def can_translate(actor: str | dict | None, source_plane: str, target_plane: str,
                  interface: dict | None = None) -> Decision:
    """Fail-closed cross-plane translation evaluator."""
    source = str(source_plane or "").lower()
    target = str(target_plane or "").lower()
    if source == target:
        return _allow("same_plane")
    if _is_llm(actor):
        return _deny("llm_cannot_translate_authoritatively", "human_review", "LLM actors cannot authorize cross-plane translation.")
    if not interface:
        return _deny(
            "plane_interface_required",
            "create_plane_interface",
            "Cross-plane movement requires a plane interface receipt that records translation loss.",
        )
    if str(interface.get("source_plane") or "").lower() != source:
        return _deny("wrong_source_plane", "create_plane_interface", "The interface source plane does not match.")
    if str(interface.get("target_plane") or "").lower() != target:
        return _deny("wrong_target_plane", "create_plane_interface", "The interface target plane does not match.")
    return _allow("interface_satisfied")

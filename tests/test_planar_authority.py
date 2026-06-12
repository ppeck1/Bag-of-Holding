from app.core.planar_authority import can_promote, can_translate, can_use


def _card(**overrides):
    card = {
        "id": "CARD:test",
        "doc_id": "doc-test",
        "plane": "informational",
        "d": 0,
        "m": "contain",
        "payload": {"confidence": 0.8, "quality": 0.8, "state": "active"},
    }
    card.update(overrides)
    return card


def test_strict_mode_excludes_subjective_cards():
    decision = can_use(
        "human_owner",
        _card(plane="subjective", payload={"confidence": 0.8, "state": "active"}),
        "answer_context",
        "Strict Answer",
    )
    assert decision.allowed is False
    assert decision.reason == "subjective_excluded"
    assert decision.required_action == "use_exploration_mode"


def test_exploration_mode_allows_subjective_cards_with_labels_elsewhere():
    decision = can_use(
        "human_owner",
        _card(plane="subjective", payload={"confidence": 0.8, "state": "active"}),
        "answer_context",
        "Exploration",
    )
    assert decision.allowed is True


def test_promotion_without_certificate_is_blocked():
    decision = can_promote("human_owner", _card(), "canonical")
    assert decision.allowed is False
    assert decision.reason == "certificate_required"
    assert decision.required_action == "request_certificate"


def test_llm_cannot_promote_even_with_certificate():
    decision = can_promote(
        {"actor_type": "llm", "actor_id": "ollama_local"},
        _card(),
        "canonical",
        certificate={"status": "approved", "card_id": "CARD:test"},
    )
    assert decision.allowed is False
    assert decision.reason == "llm_cannot_promote"


def test_valid_matching_certificate_allows_promotion():
    decision = can_promote(
        "human_owner",
        _card(),
        "canonical",
        certificate={"status": "approved", "card_id": "CARD:test"},
    )
    assert decision.allowed is True


def test_cross_plane_translation_requires_interface():
    decision = can_translate("human_owner", "subjective", "informational")
    assert decision.allowed is False
    assert decision.reason == "plane_interface_required"
    assert decision.required_action == "create_plane_interface"


def test_matching_interface_allows_translation():
    decision = can_translate(
        "human_owner",
        "subjective",
        "informational",
        interface={"source_plane": "subjective", "target_plane": "informational"},
    )
    assert decision.allowed is True

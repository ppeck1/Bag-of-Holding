"""Focused coverage for the authority-transition state machine (TASK 1.2).

metadata_contract.can_transition was previously exercised only indirectly. These
tests pin its contract: free movement among non-authoritative states, an explicit
promotion ladder, canonical immutability, and approval-gated canon promotion.
"""

import pytest

from app.core.metadata_contract import can_transition


# ---------------------------------------------------------------------------
# Allowed transitions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("old,new", [
    ("draft", "draft"),                       # same status
    ("draft", "quarantine"),                  # non-auth -> non-auth
    ("scratch", "draft"),                     # non-auth -> non-auth (and ladder)
    ("raw", "draft"),                         # raw intake
    ("draft", "review_required"),             # promotion ladder
    ("review_required", "canonical_candidate"),
    ("canonical", "superseded"),              # canonical may be retired
    ("canonical", "archived"),
    ("approved_patch", "canonical_update"),
    ("imported_non_authoritative", "draft"),
])
def test_allowed_transitions(old, new):
    ok, reason = can_transition(old, new)
    assert ok is True, f"{old}->{new} should be allowed: {reason}"


# ---------------------------------------------------------------------------
# Disallowed transitions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("old,new", [
    ("canonical", "draft"),                   # canonical cannot be demoted
    ("canonical", "canonical_candidate"),     # canonical cannot be overwritten
    ("approved", "superseded"),               # not on any ladder
    ("review_artifact", "canonical_update"),  # wrong ladder rung
    ("canonical_candidate", "draft"),         # cannot walk back down
])
def test_disallowed_transitions(old, new):
    ok, reason = can_transition(old, new)
    assert ok is False, f"{old}->{new} should be disallowed"
    assert reason  # a human-readable reason is always given


def test_overwrite_states_never_allowed():
    ok, reason = can_transition("draft", "overwritten_by_import")
    assert ok is False
    assert "never allowed" in reason.lower()


# ---------------------------------------------------------------------------
# Approval gate on canonical promotion
# ---------------------------------------------------------------------------

def test_canonical_promotion_requires_approval():
    blocked, reason = can_transition("canonical_candidate", "canonical", approved=False)
    assert blocked is False
    assert "approval" in reason.lower()

    allowed, _ = can_transition("canonical_candidate", "canonical", approved=True)
    assert allowed is True


def test_draft_to_canonical_requires_approval():
    assert can_transition("draft", "canonical", approved=False)[0] is False
    assert can_transition("draft", "canonical", approved=True)[0] is True


def test_none_old_status_treated_as_raw():
    ok, _ = can_transition(None, "draft")
    assert ok is True

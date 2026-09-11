"""Unit: pure state-transition rules. No I/O."""

import pytest

from app.domain.errors import StateTransitionInvalid
from app.domain.models import EncounterStatus as S
from app.domain.state_machine import ensure_status, ensure_transition


@pytest.mark.parametrize(
    "current,target",
    [
        (S.DRAFT, S.SUBMITTED),
        (S.SUBMITTED, S.PROCESSING),
        (S.PROCESSING, S.REVIEW_REQUIRED),
        (S.PROCESSING, S.PROCESSING_FAILED),
        (S.REVIEW_REQUIRED, S.APPROVED),
        (S.APPROVED, S.PUBLISHED),
        (S.APPROVED, S.REVIEW_REQUIRED),
        (S.PUBLISHED, S.REVOKED),
        (S.PROCESSING_FAILED, S.PROCESSING),
    ],
)
def test_allowed_transitions_pass(current, target):
    ensure_transition(current, target, action="test")


@pytest.mark.parametrize(
    "current,target",
    [
        (S.DRAFT, S.PROCESSING),
        (S.DRAFT, S.APPROVED),
        (S.REVIEW_REQUIRED, S.PUBLISHED),
        (S.PUBLISHED, S.APPROVED),
        (S.REVOKED, S.REVIEW_REQUIRED),
        (S.APPROVED, S.DRAFT),
    ],
)
def test_disallowed_transitions_raise(current, target):
    with pytest.raises(StateTransitionInvalid) as exc_info:
        ensure_transition(current, target, action="test")
    assert exc_info.value.code == "STATE_TRANSITION_INVALID"
    assert exc_info.value.http_status == 409


def test_ensure_status_rejects_unexpected_current_status():
    with pytest.raises(StateTransitionInvalid):
        ensure_status(S.DRAFT, {S.SUBMITTED, S.PROCESSING_FAILED}, action="process")


def test_ensure_status_accepts_expected_current_status():
    ensure_status(S.SUBMITTED, {S.SUBMITTED, S.PROCESSING_FAILED}, action="process")

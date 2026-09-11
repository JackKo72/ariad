"""Encounter status transition rules.

Kept as a pure lookup table + guard function so every route enforces the
same allowed transitions instead of re-deriving them ad hoc (docs/PRODUCT.md
section 6, docs/ARCHITECTURE.md data invariants).
"""

from __future__ import annotations

from app.domain.errors import StateTransitionInvalid
from app.domain.models import EncounterStatus as S

ALLOWED_TRANSITIONS: dict[S, set[S]] = {
    S.DRAFT: {S.SUBMITTED},
    S.SUBMITTED: {S.PROCESSING},
    S.PROCESSING: {S.REVIEW_REQUIRED, S.PROCESSING_FAILED},
    S.REVIEW_REQUIRED: {S.APPROVED},
    S.APPROVED: {S.PUBLISHED, S.REVIEW_REQUIRED},
    S.PUBLISHED: {S.REVOKED},
    S.PROCESSING_FAILED: {S.PROCESSING},
    S.REVOKED: set(),
}

# Draft content (PATCH /draft) may be edited while REVIEW_REQUIRED without a
# status change. Approving an already-approved encounter re-opens editing by
# moving it back to REVIEW_REQUIRED with a freshly cloned draft version.
EDITABLE_STATUSES: set[S] = {S.REVIEW_REQUIRED}


def ensure_transition(current: S, target: S, action: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise StateTransitionInvalid(current_status=current.value, action=action)


def ensure_status(current: S, expected: set[S], action: str) -> None:
    if current not in expected:
        raise StateTransitionInvalid(current_status=current.value, action=action)

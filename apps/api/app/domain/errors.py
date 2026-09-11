"""ARIAD domain error codes.

Codes marked (task-01) are generic state-machine guards this vertical slice
needs but that docs/DEBUGGING.md's taxonomy does not cover (that taxonomy is
written for the audio/ASR pipeline in tasks/02_AUDIO_PIPELINE.md).
"""

from __future__ import annotations


class AriadError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable


class StateTransitionInvalid(AriadError):
    def __init__(self, current_status: str, action: str):
        super().__init__(
            code="STATE_TRANSITION_INVALID",
            message=f"Cannot perform '{action}' while encounter is in status '{current_status}'.",
            http_status=409,
            retryable=False,
        )


class ApprovalStaleVersion(AriadError):
    def __init__(self):
        super().__init__(
            code="APPROVAL_STALE_VERSION",
            message="The draft has changed since you loaded it. Reload and try again.",
            http_status=409,
            retryable=False,
        )


class PublishNotApproved(AriadError):
    def __init__(self):
        super().__init__(
            code="PUBLISH_NOT_APPROVED",
            message="Encounter must be approved before it can be published.",
            http_status=409,
            retryable=False,
        )


class ValidationUnsupportedClaim(AriadError):
    def __init__(self, detail: str):
        super().__init__(
            code="VALIDATION_UNSUPPORTED_CLAIM",
            message=detail,
            http_status=422,
            retryable=False,
        )


class NotFoundError(AriadError):
    def __init__(self, entity: str):
        super().__init__(
            code="NOT_FOUND",
            message=f"{entity} not found.",
            http_status=404,
            retryable=False,
        )

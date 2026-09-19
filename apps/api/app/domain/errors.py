"""ARIAD domain error codes.

Codes marked (task-01) are generic state-machine guards this vertical slice
needs but that docs/DEBUGGING.md's taxonomy does not cover (that taxonomy is
written for the audio/ASR pipeline in tasks/02_AUDIO_PIPELINE.md). The
AUDIO_* codes below are that taxonomy's Phase A (upload validation) subset --
see tasks/02_AUDIO_PIPELINE.md section 5.
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


class AudioFileTooLarge(AriadError):
    def __init__(self, max_bytes: int):
        super().__init__(
            code="AUDIO_FILE_TOO_LARGE",
            message=f"Audio file exceeds the {max_bytes // (1024 * 1024)} MB limit.",
            http_status=413,
            retryable=False,
        )


class AudioDurationTooLong(AriadError):
    def __init__(self, max_minutes: int):
        super().__init__(
            code="AUDIO_DURATION_TOO_LONG",
            message=f"Audio duration exceeds the {max_minutes}-minute development limit.",
            http_status=422,
            retryable=False,
        )


class AudioUnsupportedFormat(AriadError):
    def __init__(self, detected: str | None):
        super().__init__(
            code="AUDIO_UNSUPPORTED_FORMAT",
            message=f"Unsupported audio format (detected: {detected or 'unknown'}).",
            http_status=422,
            retryable=False,
        )


class AudioStreamMissing(AriadError):
    def __init__(self):
        super().__init__(
            code="AUDIO_STREAM_MISSING",
            message="The uploaded file has no usable audio stream.",
            http_status=422,
            retryable=False,
        )


class AudioProbeFailed(AriadError):
    def __init__(self):
        super().__init__(
            code="AUDIO_PROBE_FAILED",
            message="The uploaded file could not be read as media.",
            http_status=422,
            retryable=False,
        )


class AudioConversionFailed(AriadError):
    def __init__(self):
        super().__init__(
            code="AUDIO_CONVERSION_FAILED",
            message="Audio standardization/preprocessing failed.",
            http_status=422,
            retryable=True,
        )


class AsrNotConfigured(AriadError):
    def __init__(self):
        super().__init__(
            code="ASR_NOT_CONFIGURED",
            message="ASR provider가 설정되지 않았습니다. 전사문을 직접 입력해 계속 진행할 수 있습니다.",
            http_status=422,
            retryable=False,
        )

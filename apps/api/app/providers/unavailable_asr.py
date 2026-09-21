"""Fallback ASR provider for an arbitrary upload when no real ASR provider
is configured (tasks/02_AUDIO_PIPELINE.md section 3.2). Always raises
ASR_NOT_CONFIGURED with a clear, actionable message rather than a blank
screen -- the clinician can still type the transcript manually and continue
through the existing Task 01 flow.
"""

from __future__ import annotations

from app.domain.errors import AsrNotConfigured
from app.domain.models import AudioAsset, DiarizedSegment


class UnavailableASRProvider:
    """See app.providers.asr_base.ASRProvider."""

    def transcribe(self, audio_asset: AudioAsset, storage_path: str) -> list[DiarizedSegment]:
        raise AsrNotConfigured()

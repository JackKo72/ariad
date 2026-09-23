"""ASR provider boundary (tasks/02_AUDIO_PIPELINE.md section 8).

Mirrors app/providers/base.py's LLMProvider pattern: routes depend only on
this Protocol so a real ASR provider can be swapped in (Phase D) without
touching domain, route, or pipeline code.
"""

from __future__ import annotations

from typing import Optional, Protocol

from app.domain.models import AudioAsset, DiarizedSegment
from app.observability import StageTimer


class ASRProvider(Protocol):
    def transcribe(
        self, audio_asset: AudioAsset, storage_path: str, stage_timer: Optional[StageTimer] = None
    ) -> list[DiarizedSegment]: ...

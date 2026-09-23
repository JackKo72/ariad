"""structure_encounter pipeline stage (docs/ARCHITECTURE.md section 5)."""

from __future__ import annotations

from typing import Optional

from app.domain.models import ClinicalStructure
from app.observability import StageTimer
from app.providers.base import LLMProvider
from app.providers.mock import PROMPT_VERSION_STRUCTURE


def structure_encounter(
    transcript_text: str, llm_provider: LLMProvider, stage_timer: Optional[StageTimer] = None
) -> ClinicalStructure:
    raw = llm_provider.generate_json(
        "structure_transcript", {"transcript_text": transcript_text}, stage_timer=stage_timer
    )
    return ClinicalStructure.model_validate(raw)


PROMPT_VERSION = PROMPT_VERSION_STRUCTURE

"""structure_encounter pipeline stage (docs/ARCHITECTURE.md section 5)."""

from __future__ import annotations

from app.domain.models import ClinicalStructure
from app.providers.base import LLMProvider
from app.providers.mock import PROMPT_VERSION_STRUCTURE


def structure_encounter(transcript_text: str, llm_provider: LLMProvider) -> ClinicalStructure:
    raw = llm_provider.generate_json("structure_transcript", {"transcript_text": transcript_text})
    return ClinicalStructure.model_validate(raw)


PROMPT_VERSION = PROMPT_VERSION_STRUCTURE

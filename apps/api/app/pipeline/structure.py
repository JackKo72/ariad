"""structure_encounter pipeline stage (docs/ARCHITECTURE.md section 5)."""

from __future__ import annotations

from typing import Optional

from app.domain.models import ClinicalFrameId, ClinicalStructure
from app.observability import StageTimer
from app.pipeline.frames import load_frame, validate_term_candidates
from app.providers.base import LLMProvider
from app.providers.mock import PROMPT_VERSION_STRUCTURE


def structure_encounter(
    transcript_text: str,
    llm_provider: LLMProvider,
    stage_timer: Optional[StageTimer] = None,
    clinical_frame: Optional[ClinicalFrameId] = None,
) -> ClinicalStructure:
    """`clinical_frame` (tasks/10): the clinician-selected frame; its
    vocabulary file goes to the LLM, and term candidates outside it are
    dropped after the call."""
    payload: dict = {"transcript_text": transcript_text}
    if clinical_frame is not None:
        payload["clinical_frame"] = load_frame(clinical_frame)
    raw = llm_provider.generate_json("structure_transcript", payload, stage_timer=stage_timer)
    return validate_term_candidates(ClinicalStructure.model_validate(raw), clinical_frame, transcript_text)


PROMPT_VERSION = PROMPT_VERSION_STRUCTURE

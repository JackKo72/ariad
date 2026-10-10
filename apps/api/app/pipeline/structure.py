"""structure_encounter pipeline stage (docs/ARCHITECTURE.md section 5)."""

from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from app.domain.models import ClinicalStructure
from app.observability import StageTimer
from app.pipeline.directive_validation import validate_action_directives
from app.pipeline.segments import Segment, segments_from_transcript_text
from app.providers.base import LLMProvider
from app.providers.mock import PROMPT_VERSION_STRUCTURE


def structure_encounter(
    transcript_text: str,
    llm_provider: LLMProvider,
    stage_timer: Optional[StageTimer] = None,
    segments: Optional[list[Segment]] = None,
) -> ClinicalStructure:
    # docs/stage1_output.md section 6 (option C): the LLM also gets the
    # segments so it can copy real IDs; manual text gets seg_001.. per line.
    if segments is None:
        segments = segments_from_transcript_text(transcript_text)
    payload = {"transcript_text": transcript_text, "segments": segments}
    # CLAUDE.md stage 2 rule: retry an invalid LLM output once. A second
    # failure propagates to the existing PROCESSING_FAILED path, where the
    # clinician can retry or edit the draft by hand.
    try:
        structure = ClinicalStructure.model_validate(
            llm_provider.generate_json("structure_transcript", payload, stage_timer=stage_timer)
        )
    except ValidationError:
        structure = ClinicalStructure.model_validate(
            llm_provider.generate_json("structure_transcript", payload, stage_timer=stage_timer)
        )
    return structure.model_copy(
        update={"action_directives": validate_action_directives(structure.action_directives, segments)}
    )


PROMPT_VERSION = PROMPT_VERSION_STRUCTURE

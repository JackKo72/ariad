"""structure_encounter pipeline stage (docs/ARCHITECTURE.md section 5)."""

from __future__ import annotations

from typing import Optional

from app.domain.models import ClinicalFrameId, ClinicalStructure, TermCandidate, TermCandidateList
from app.observability import StageTimer
from app.pipeline.frames import load_frame, validate_term_candidates
from app.providers.base import LLMProvider
from app.providers.mock import PROMPT_VERSION_STRUCTURE, PROMPT_VERSION_TERM_CANDIDATES


def structure_encounter(
    transcript_text: str,
    llm_provider: LLMProvider,
    stage_timer: Optional[StageTimer] = None,
    clinical_frame: Optional[ClinicalFrameId] = None,
) -> ClinicalStructure:
    """`clinical_frame` (tasks/10): the clinician-selected frame.

    tasks/13-c: two calls. The structure call gets the transcript only and
    its term_candidates are discarded; when a frame is selected, a separate
    call gets the transcript + frame vocabulary and does nothing but find
    term candidates. Measured on the 13-minute ER role-play, one combined
    call spent its fixed output budget on the slots and returned zero
    suspected-diagnosis candidates in 3/3 runs."""
    raw = llm_provider.generate_json("structure_transcript", {"transcript_text": transcript_text},
                                     stage_timer=stage_timer)
    structure = ClinicalStructure.model_validate(raw)
    candidates = (
        extract_term_candidates(transcript_text, llm_provider, clinical_frame, stage_timer)
        if clinical_frame is not None
        else []
    )
    return structure.model_copy(update={"term_candidates": candidates})


def extract_term_candidates(
    transcript_text: str,
    llm_provider: LLMProvider,
    clinical_frame: ClinicalFrameId,
    stage_timer: Optional[StageTimer] = None,
) -> list[TermCandidate]:
    raw = llm_provider.generate_json(
        "term_candidates",
        {"transcript_text": transcript_text, "clinical_frame": load_frame(clinical_frame)},
        stage_timer=stage_timer,
    )
    found = TermCandidateList.model_validate(raw).term_candidates
    # Same mechanical checks as before: selected frame, vocabulary term,
    # verbatim quote; risk overwritten from the vocabulary.
    return validate_term_candidates(ClinicalStructure(term_candidates=found), clinical_frame,
                                    transcript_text).term_candidates


# Both prompts shape the stored structure, so both versions are recorded.
PROMPT_VERSION = f"{PROMPT_VERSION_STRUCTURE}+{PROMPT_VERSION_TERM_CANDIDATES}"

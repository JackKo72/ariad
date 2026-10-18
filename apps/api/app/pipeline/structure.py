"""structure_encounter pipeline stage (docs/ARCHITECTURE.md section 5)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from pydantic import ValidationError

from app.domain.models import ClinicalFrameId, ClinicalStructure, TermCandidate, TermCandidateList
from app.observability import StageTimer
from app.pipeline.directive_validation import validate_action_directives
from app.pipeline.frame_checks import check_frame_items
from app.pipeline.frames import load_frame, validate_term_candidates
from app.pipeline.segments import Segment, segments_from_transcript_text
from app.providers.base import LLMProvider
from app.providers.mock import (
    PROMPT_VERSION_COVERAGE,
    PROMPT_VERSION_FRAME_CHECKLIST,
    PROMPT_VERSION_STRUCTURE,
    PROMPT_VERSION_TERM_CANDIDATES,
)


def structure_encounter(
    transcript_text: str,
    llm_provider: LLMProvider,
    stage_timer: Optional[StageTimer] = None,
    clinical_frame: Optional[ClinicalFrameId] = None,
    segments: Optional[list[Segment]] = None,
) -> ClinicalStructure:
    """`clinical_frame` (tasks/10): the clinician-selected frame.

    tasks/13-c: two calls. The structure call gets the transcript only and
    its term_candidates are discarded; when a frame is selected, a separate
    call gets the transcript + frame vocabulary and does nothing but find
    term candidates. Measured on the 13-minute ER role-play, one combined
    call spent its fixed output budget on the slots and returned zero
    suspected-diagnosis candidates in 3/3 runs.

    tasks/13-e: a coverage call between them adds what the structure call
    left out (see add_missed_facts).

    tasks/14: with a frame that has a must-check list, a last call marks
    which list items the encounter covered (app/pipeline/frame_checks.py).

    tasks/15: only coverage needs another call's output, so three branches
    run at once -- structure -> coverage | term candidates | frame checks.
    Any branch's error is re-raised here, as before.

    `segments` (docs/stage1_output.md section 6, option C): the structure
    call also gets the segments so its action_directives can copy real IDs;
    manual text gets seg_001.. per line. Directives are grounding-checked
    once, after all branches are merged."""
    if segments is None:
        segments = segments_from_transcript_text(transcript_text)
    with ThreadPoolExecutor(max_workers=3) as pool:
        slots = pool.submit(_structure_and_coverage, transcript_text, segments, llm_provider, stage_timer)
        terms = checks = None
        if clinical_frame is not None:
            terms = pool.submit(extract_term_candidates, transcript_text, llm_provider, clinical_frame, stage_timer)
            checks = pool.submit(check_frame_items, transcript_text, llm_provider, clinical_frame, stage_timer)
        structure = slots.result()
        return structure.model_copy(update={
            "term_candidates": terms.result() if terms else [],
            "frame_checks": checks.result() if checks else [],
            "action_directives": validate_action_directives(structure.action_directives, segments),
        })


def _structure_and_coverage(
    transcript_text: str, segments: list[Segment], llm_provider: LLMProvider, stage_timer: Optional[StageTimer]
) -> ClinicalStructure:
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
    return add_missed_facts(transcript_text, structure, llm_provider, stage_timer)


# Fields the coverage call neither sees nor adds to: each has its own call
# (term_candidates, frame_checks) or its own grounding check (action_directives).
_NOT_COVERAGE_FIELDS = {"term_candidates", "frame_checks", "action_directives"}


def add_missed_facts(
    transcript_text: str,
    structure: ClinicalStructure,
    llm_provider: LLMProvider,
    stage_timer: Optional[StageTimer] = None,
) -> ClinicalStructure:
    """tasks/13-e: the structure call keeps 1-3 items per slot and drops the
    rest outright (make diagnose-structure on the ER/MG role-plays: 62-68%
    of misses had no keyword in any summary item, the same items in 3/3
    runs, despite slot rules for them). A second call sees the transcript
    and the structure and returns only what is missing, in the same schema;
    it is appended. Term candidates, frame checks and action directives are
    not this call's job and are dropped."""
    raw = llm_provider.generate_json(
        "coverage_check",
        {"transcript_text": transcript_text,
         "structure": structure.model_dump(exclude=_NOT_COVERAGE_FIELDS)},
        stage_timer=stage_timer,
    )
    missed = ClinicalStructure.model_validate(raw)
    update = {}
    for field in ClinicalStructure.model_fields:
        if field in _NOT_COVERAGE_FIELDS:
            continue
        existing = getattr(structure, field)
        seen = {_dedup_key(item) for item in existing}
        added = [item for item in getattr(missed, field) if _dedup_key(item) not in seen]
        if added:
            update[field] = [*existing, *added]
    return structure.model_copy(update=update)


def _dedup_key(item: Any) -> str:
    """Exact repeats only (case and spacing ignored); the prompt is what
    keeps paraphrased repeats out."""
    if isinstance(item, str):
        values = [item]
    else:
        values = [v for k, v in item.model_dump().items() if isinstance(v, str) and k != "source_segment_ids"]
    return "|".join("".join(v.lower().split()) for v in values)


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


# Every prompt that shapes the stored structure is recorded.
PROMPT_VERSION = "+".join([PROMPT_VERSION_STRUCTURE, PROMPT_VERSION_COVERAGE, PROMPT_VERSION_TERM_CANDIDATES,
                           PROMPT_VERSION_FRAME_CHECKLIST])

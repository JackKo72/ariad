"""generate_patient_explanation pipeline stage (docs/ARCHITECTURE.md section 5)."""

from __future__ import annotations

from typing import Optional

from app.domain.models import ClinicalStructure, ExplanationDraft
from app.observability import StageTimer
from app.providers.base import LLMProvider
from app.providers.mock import PROMPT_VERSION_EXPLANATION


def generate_patient_explanation(
    structure: ClinicalStructure, llm_provider: LLMProvider, stage_timer: Optional[StageTimer] = None
) -> ExplanationDraft:
    # tasks/10: term candidates are unreviewed clinical-term guesses for the
    # clinician; they never feed patient-facing text.
    patient_safe = structure.model_copy(update={"term_candidates": []})
    raw = llm_provider.generate_json(
        "patient_explanation", {"structure": patient_safe.model_dump()}, stage_timer=stage_timer
    )
    return ExplanationDraft.model_validate(raw)


PROMPT_VERSION = PROMPT_VERSION_EXPLANATION

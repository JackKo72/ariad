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
    raw = llm_provider.generate_json(
        "patient_explanation", {"structure": structure.model_dump()}, stage_timer=stage_timer
    )
    return ExplanationDraft.model_validate(raw)


PROMPT_VERSION = PROMPT_VERSION_EXPLANATION

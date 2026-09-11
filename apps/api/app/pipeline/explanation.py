"""generate_patient_explanation pipeline stage (docs/ARCHITECTURE.md section 5)."""

from __future__ import annotations

from app.domain.models import ClinicalStructure, ExplanationDraft
from app.providers.base import LLMProvider
from app.providers.mock import PROMPT_VERSION_EXPLANATION


def generate_patient_explanation(structure: ClinicalStructure, llm_provider: LLMProvider) -> ExplanationDraft:
    raw = llm_provider.generate_json("patient_explanation", {"structure": structure.model_dump()})
    return ExplanationDraft.model_validate(raw)


PROMPT_VERSION = PROMPT_VERSION_EXPLANATION

"""run_pipeline: orchestrates structure -> explanation for the current draft.

Grounding validation runs at approve time (see app/routes/encounters.py),
not here -- see docs/TESTING_AND_EVALS.md non-negotiable gate: "근거 없는
중요 임상사실 0건"을 승인 시점에 강제한다. Audio/ASR/diarization stages from
docs/ARCHITECTURE.md section 5 are out of scope for tasks/01_VERTICAL_SLICE.md
and intentionally omitted.
"""

from __future__ import annotations

from typing import Optional

from app.domain.models import PipelineResult
from app.observability import StageTimer
from app.pipeline.explanation import generate_patient_explanation
from app.pipeline.structure import structure_encounter
from app.providers.base import LLMProvider


def run_pipeline(
    transcript_text: str, llm_provider: LLMProvider, stage_timer: Optional[StageTimer] = None
) -> PipelineResult:
    structure = structure_encounter(transcript_text, llm_provider, stage_timer)
    explanation = generate_patient_explanation(structure, llm_provider, stage_timer)
    return PipelineResult(success=True, structure=structure, explanation=explanation)

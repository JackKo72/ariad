"""clinical_enrichment pipeline stage (tasks/04_CLINICAL_ENRICHMENT.md).

Sits between the ASR/diarization transcript and structure_encounter
(docs/ARCHITECTURE.md section 5) -- purely additive, never replaces
transcript_text or ClinicalStructure. Only meaningful when segment-level
speaker/time metadata exists (audio-derived PipelineRun.segments);
app/routes/encounters.py skips this stage entirely for manual text-only
encounters and demo mode.
"""

from __future__ import annotations

from typing import Optional

from app.domain.models import ClinicalEnrichment, DiarizedSegment
from app.observability import StageTimer
from app.pipeline.enrichment_validation import validate_enrichment
from app.providers.base import LLMProvider
from app.providers.mock import PROMPT_VERSION_ENRICHMENT


def _segment_payload(segments: list[DiarizedSegment]) -> list[dict]:
    return [
        {
            "id": seg.id,
            "speaker": seg.speaker,
            "role": seg.role,
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
        }
        for seg in sorted(segments, key=lambda s: s.start)
    ]


def enrich_clinical_findings(
    segments: list[DiarizedSegment],
    llm_provider: LLMProvider,
    stage_timer: Optional[StageTimer] = None,
) -> ClinicalEnrichment:
    raw = llm_provider.generate_json(
        "clinical_enrichment", {"segments": _segment_payload(segments)}, stage_timer=stage_timer
    )
    enrichment = ClinicalEnrichment.model_validate(raw)
    return validate_enrichment(enrichment, segments)


PROMPT_VERSION = PROMPT_VERSION_ENRICHMENT

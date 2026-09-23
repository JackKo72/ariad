"""Deterministic mock LLM provider.

Default local provider (docs/ARCHITECTURE.md section 6, docs/LOCAL_DEVELOPMENT.md
ARIAD_MODE=mock). Never calls an external API. Given the same input it always
returns the same output, and it only ever copies text that is already present
in the transcript -- it never invents diagnoses, medications, doses, or dates
(docs/CLAUDE.md medical/privacy rules).
"""

from __future__ import annotations

from typing import Any, Optional

from app.observability import StageTimer

PROMPT_VERSION_STRUCTURE = "structure_transcript@0.1.0"
PROMPT_VERSION_EXPLANATION = "patient_explanation@0.1.0"


def _segment_transcript(transcript_text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in transcript_text.splitlines() if line.strip()]
    return [{"id": f"seg-{i + 1}", "text": line} for i, line in enumerate(lines)]


class MockLLMProvider:
    """Local-mode LLMProvider. See app.providers.base.LLMProvider."""

    def generate_json(
        self, prompt_id: str, payload: dict[str, Any], stage_timer: Optional[StageTimer] = None
    ) -> dict[str, Any]:
        # stage_timer is unused here -- in-process, no network/model, not
        # worth instrumenting on its own (route-level timers already cover
        # the surrounding structure_llm/explanation_llm stage duration).
        if prompt_id == "structure_transcript":
            return self._structure_transcript(payload)
        if prompt_id == "patient_explanation":
            return self._patient_explanation(payload)
        raise ValueError(f"MockLLMProvider has no handler for prompt_id={prompt_id!r}")

    def _structure_transcript(self, payload: dict[str, Any]) -> dict[str, Any]:
        segments = _segment_transcript(payload["transcript_text"])
        problems = [
            {"text": seg["text"], "certainty": "stated", "source_segment_ids": [seg["id"]]}
            for seg in segments
        ]
        return {
            "problems": problems,
            "tests": [],
            "medications": [],
            "plan": [],
            "warnings": [],
            "follow_up": [],
            "questions_or_conflicts": [],
        }

    def _patient_explanation(self, payload: dict[str, Any]) -> dict[str, Any]:
        structure = payload["structure"]
        situation_texts = [p["text"] for p in structure.get("problems", [])]
        source_segment_ids = [
            sid for p in structure.get("problems", []) for sid in p.get("source_segment_ids", [])
        ]
        return {
            "draft_notice": "의료진 검토 전 초안입니다.",
            "current_situation": situation_texts,
            "tests_and_reasons": [],
            "treatment_plan": [],
            "medication_instructions": [],
            "warning_signs": [],
            "what_to_do_next": [],
            "follow_up": [],
            "items_to_confirm_with_clinician": [],
            "source_map": [{"field": "current_situation", "source_segment_ids": source_segment_ids}],
        }

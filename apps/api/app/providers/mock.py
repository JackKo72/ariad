"""Deterministic mock LLM provider.

Default local provider (docs/ARCHITECTURE.md section 6, docs/LOCAL_DEVELOPMENT.md
ARIAD_MODE=mock). Never calls an external API. Given the same input it always
returns the same output, and it only ever copies text that is already present
in the transcript -- it never invents diagnoses, medications, doses, or dates
(docs/CLAUDE.md medical/privacy rules).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.observability import StageTimer
from app.pipeline.asr_normalize import contains_number_word

PROMPT_VERSION_STRUCTURE = "structure_transcript@0.6.0"
PROMPT_VERSION_EXPLANATION = "patient_explanation@0.1.0"
PROMPT_VERSION_ENRICHMENT = "clinical_enrichment@0.1.0"
PROMPT_VERSION_TERM_CANDIDATES = "term_candidates@0.2.0"

_DOSE_UNIT_RE = re.compile(r"(밀리그램|mg|(?<!킬로)그램)")
_MEDICATION_MENTION_RE = re.compile(r"약")
_MEDICATION_ACTION_HINT_RE = re.compile(r"(끊|중단|시작|드시|복용)")
_QUESTION_RE = re.compile(r"(나요|까요|습니까)\s*[?？]?\s*$|\?\s*$")
_EXAM_ORDER_RE = re.compile(r"(들어보세요|해보세요|보여주세요|해보실까요)")
# Narrow, safe-by-construction additions: only fire when the doctor's own
# words already contain an explicit score/diagnosis -- never inferred, only
# copied verbatim, so grounding is guaranteed by construction.
_EXPLICIT_SCORE_RE = re.compile(r"(NIHSS|mRS|MRC).{0,12}\d+\s*점")
_EXPLICIT_DIAGNOSIS_RE = re.compile(r"진단은")
# tasks/06_ASR_OUTPUT_VERIFICATION.md: vital-sign (blood pressure, weight,
# temperature, pulse, blood glucose) reading detection. Mentioning the
# keyword alone (an order/question, e.g. "혈압을 재볼까요?") never
# produces a value_candidate -- only a sentence that also already has a
# number does, and the candidate is the whole segment text verbatim (same
# convention _EXPLICIT_SCORE_RE already uses), never a value the mock
# parses/computes out of it.
_VITAL_SIGN_KEYWORD_RE = re.compile(r"(혈압|체중|체온|맥박|혈당)")
_STOP_WORD_RE = re.compile(r"(끊|중단)")
_NEGATED_STOP_RE = re.compile(r"(끊지|중단하지|멈추지)\s*(마세요|말고|말아)")
_PATIENT_SYMPTOM_RE = re.compile(r"(증상|아프|힘들|못\s*자|저리|어지럽)")
_NOCTURNAL_BEHAVIOR_RE = re.compile(r"(잠꼬대|소리를\s*지르|팔다리를\s*휘|발로\s*차|몸부림)")
_DOCTOR_DIRECTIVE_RE = re.compile(r"(하겠습니다|하시고|오세요|가셔야)")


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
        if prompt_id == "clinical_enrichment":
            return self._clinical_enrichment(payload)
        if prompt_id == "term_candidates":
            # Never maps lay words to terms -- that needs a real model.
            return {"term_candidates": []}
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
            # tasks/10 slots: the mock never interprets, so it never fills
            # decisions or proposes frame terms.
            "treatments_given": [],
            "findings": [],
            "decisions": [],
            "consents": [],
            "disposition": [],
            "prognosis_and_goals": [],
            "family_statements": [],
            "term_candidates": [],
        }

    def _clinical_enrichment(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Deterministic, rule-based stand-in for the real LLM (same spirit
        as _structure_transcript: never invents content, only classifies
        text that's already in the segment). Safe by construction against
        the four forbidden patterns in prompts/clinical_enrichment.md --
        not by being clever, but by never having the capability to violate
        them: exam findings only ever get a score when the doctor's own
        words already contain one verbatim (never inferred from an order
        alone), diagnoses only ever get created when the doctor explicitly
        used the word "진단" (never inferred from a patient/guardian
        description alone), doctor questions never become anything but a
        question, and the one negation pattern it checks flips continue
        instead of stop."""
        segments = payload["segments"]
        medications: list[dict[str, Any]] = []
        symptoms: list[dict[str, Any]] = []
        exam: list[dict[str, Any]] = []
        diagnoses: list[dict[str, Any]] = []
        plan: list[dict[str, Any]] = []
        follow_up_questions: list[dict[str, Any]] = []

        def source_span(seg: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                {
                    "segment_id": seg["id"],
                    "quote": seg["text"],
                    "speaker": seg["speaker"],
                    "role": seg.get("role", "unknown"),
                    "start": seg.get("start"),
                    "end": seg.get("end"),
                }
            ]

        for seg in segments:
            text = seg["text"]
            role = seg.get("role", "unknown")

            has_dose_unit = bool(_DOSE_UNIT_RE.search(text))
            has_bare_medication_mention = bool(
                _MEDICATION_MENTION_RE.search(text) and _MEDICATION_ACTION_HINT_RE.search(text)
            )
            if has_dose_unit or has_bare_medication_mention:
                negated_continue = bool(_NEGATED_STOP_RE.search(text))
                if negated_continue:
                    action, polarity = "continue", "negated"
                elif _STOP_WORD_RE.search(text):
                    action, polarity = "stop", "affirmed"
                elif "시작" in text:
                    action, polarity = "start", "affirmed"
                else:
                    action, polarity = "unknown", "affirmed"
                medications.append(
                    {
                        "id": f"med-{seg['id']}",
                        "raw_text": text,
                        "name_candidates": [],
                        "ingredient_or_brand": "unknown",
                        "dose_candidates": [],
                        "route": None,
                        "frequency": None,
                        "timing": None,
                        "action": action,
                        "polarity": polarity,
                        "rationale": (
                            "용량 단위 표현 감지 (mock, 규칙 기반)"
                            if has_dose_unit
                            else "약물 관련 표현 감지, 용량 단위 없음 (mock, 규칙 기반)"
                        ),
                        "needs_review": True,
                        "source_spans": source_span(seg),
                    }
                )
                continue

            if role == "doctor" and _EXPLICIT_SCORE_RE.search(text):
                exam.append(
                    {
                        "id": f"exam-{seg['id']}",
                        "raw_text": text,
                        "kind": "observation",
                        "test_name_candidates": [],
                        "score_computable": True,
                        "score_candidates": [{"value": text, "confidence": "medium"}],
                        "rationale": "원문에 점수 표현이 그대로 포함되어 있음 (mock, 규칙 기반)",
                        "needs_review": True,
                        "source_spans": source_span(seg),
                    }
                )
                continue

            if role == "doctor":
                vital_keywords = _VITAL_SIGN_KEYWORD_RE.findall(text)
                if vital_keywords:
                    distinct_keywords = list(dict.fromkeys(vital_keywords))
                    has_number = contains_number_word(text)
                    # Two+ different vital-sign keywords with numbers in
                    # one sentence is exactly the "ownership ambiguity"
                    # case tasks/06 flagged (which number belongs to which
                    # keyword) -- still reported so a clinician sees it,
                    # but at low confidence; mock never guesses the pairing.
                    confidence = "low" if len(distinct_keywords) > 1 else "medium"
                    exam.append(
                        {
                            "id": f"exam-{seg['id']}",
                            "raw_text": text,
                            "kind": "observation" if has_number else "order",
                            "test_name_candidates": [
                                {"value": k, "confidence": "medium"} for k in distinct_keywords
                            ],
                            "score_computable": False,
                            "score_candidates": [],
                            "value_candidates": (
                                [{"value": text, "confidence": confidence}] if has_number else []
                            ),
                            "rationale": (
                                "생체 신호 키워드와 숫자가 같은 문장에 있어 관찰값 후보로 표시 (mock, 규칙 기반)"
                                if has_number and confidence == "medium"
                                else "생체 신호 키워드가 2개 이상이라 어느 숫자가 어느 항목인지 불확실 (mock, 규칙 기반)"
                                if has_number
                                else "생체 신호 키워드만 있고 숫자 없음 -- 지시/질문으로 처리 (mock, 규칙 기반)"
                            ),
                            "needs_review": True,
                            "source_spans": source_span(seg),
                        }
                    )
                    continue

            if role == "doctor" and _EXPLICIT_DIAGNOSIS_RE.search(text):
                diagnoses.append(
                    {
                        "id": f"dx-{seg['id']}",
                        "raw_text": text,
                        "kind": "confirmed",
                        "polarity": "affirmed",
                        "normalized_candidates": [],
                        "rationale": '원문에 "진단은" 표현이 그대로 포함되어 있음 (mock, 규칙 기반)',
                        "needs_review": True,
                        "source_spans": source_span(seg),
                    }
                )
                continue

            if role == "doctor" and _EXAM_ORDER_RE.search(text):
                exam.append(
                    {
                        "id": f"exam-{seg['id']}",
                        "raw_text": text,
                        "kind": "order",
                        "test_name_candidates": [],
                        "score_computable": False,
                        "score_candidates": [],
                        "rationale": "검사 지시 문구 감지, mock은 점수를 생성하지 않음",
                        "needs_review": True,
                        "source_spans": source_span(seg),
                    }
                )
                continue

            if role == "doctor" and _QUESTION_RE.search(text):
                symptoms.append(
                    {
                        "id": f"sym-{seg['id']}",
                        "raw_text": text,
                        "reported_by": "doctor_question",
                        "polarity": "question",
                        "normalized_candidates": [],
                        "rationale": "의사 질문 형태 감지, 답변 segment 없이는 확정하지 않음",
                        "needs_review": True,
                        "source_spans": source_span(seg),
                    }
                )
                continue

            if role in ("patient", "guardian"):
                nocturnal = bool(_NOCTURNAL_BEHAVIOR_RE.search(text))
                if nocturnal:
                    follow_up_questions.append(
                        {
                            "id": f"fu-{seg['id']}",
                            "trigger_text": text,
                            "suggested_question": "야간 수면 중 행동에 대해 신경과적으로 추가 확인이 필요한지 확인이 필요합니다.",
                            "rationale": "구체적 야간 행동 언급, 의사가 진단을 명시하지 않아 진단 대신 확인 후보로 표시 (mock)",
                            "needs_review": True,
                            "source_spans": source_span(seg),
                        }
                    )
                if nocturnal or _PATIENT_SYMPTOM_RE.search(text):
                    negated = any(marker in text for marker in ("안 ", "않", "못"))
                    symptoms.append(
                        {
                            "id": f"sym-{seg['id']}",
                            "raw_text": text,
                            "reported_by": "guardian" if role == "guardian" else "patient",
                            "polarity": "negated" if negated else "affirmed",
                            "normalized_candidates": [],
                            "rationale": "환자/보호자 진술 감지 (mock, 규칙 기반)",
                            "needs_review": True,
                            "source_spans": source_span(seg),
                        }
                    )
                continue

            if role == "doctor" and _DOCTOR_DIRECTIVE_RE.search(text):
                plan.append(
                    {
                        "id": f"plan-{seg['id']}",
                        "raw_text": text,
                        "kind": "directive",
                        "polarity": "affirmed",
                        "rationale": "의료진 지시 표현 감지 (mock, 규칙 기반)",
                        "needs_review": True,
                        "source_spans": source_span(seg),
                    }
                )

        return {
            "medications": medications,
            "symptoms": symptoms,
            "exam": exam,
            "diagnoses": diagnoses,
            "follow_up_questions": follow_up_questions,
            "plan": plan,
            "validator_violations": [],
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

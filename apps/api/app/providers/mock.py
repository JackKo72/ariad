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

PROMPT_VERSION_STRUCTURE = "structure_transcript@0.2.0"
PROMPT_VERSION_EXPLANATION = "patient_explanation@0.1.0"
PROMPT_VERSION_ENRICHMENT = "clinical_enrichment@0.1.0"
PROMPT_VERSION_CLASSIFY_DIRECTIVE = "classify_action_directive@0.1.0"

_DOSE_UNIT_RE = re.compile(r"(밀리그램|mg|그램)")
_MEDICATION_MENTION_RE = re.compile(r"약")
_MEDICATION_ACTION_HINT_RE = re.compile(r"(끊|중단|시작|드시|복용)")
_QUESTION_RE = re.compile(r"(나요|까요|습니까)\s*[?？]?\s*$|\?\s*$")
_EXAM_ORDER_RE = re.compile(r"(들어보세요|해보세요|보여주세요|해보실까요)")
# Narrow, safe-by-construction additions: only fire when the doctor's own
# words already contain an explicit score/diagnosis -- never inferred, only
# copied verbatim, so grounding is guaranteed by construction.
_EXPLICIT_SCORE_RE = re.compile(r"(NIHSS|mRS|MRC).{0,12}\d+\s*점")
_EXPLICIT_DIAGNOSIS_RE = re.compile(r"진단은")
_STOP_WORD_RE = re.compile(r"(끊|중단)")
_NEGATED_STOP_RE = re.compile(r"(끊지|중단하지|멈추지)\s*(마세요|말고|말아)")
_PATIENT_SYMPTOM_RE = re.compile(r"(증상|아프|힘들|못\s*자|저리|어지럽)")
_NOCTURNAL_BEHAVIOR_RE = re.compile(r"(잠꼬대|소리를\s*지르|팔다리를\s*휘|발로\s*차|몸부림)")
_DOCTOR_DIRECTIVE_RE = re.compile(r"(하겠습니다|하시고|오세요|가셔야)")


# Stage 2 action directives (prompts/structure_transcript.md 0.2.0). Keyword
# -> catalog domain (catalog/actions.yaml `domain`). A mock heuristic, not a
# clinical rule: it only decides which doctor sentences to copy verbatim.
# Checked in order, most specific first ("호흡 운동" is stress, not walking).
_DIRECTIVE_DOMAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (domain, re.compile(pattern))
    for domain, pattern in (
        ("home_bp", r"혈압.{0,15}(재|측정|기록)|혈압계"),
        ("home_glucose", r"혈당.{0,15}(재|측정|기록)|혈당계"),
        ("smoking", r"담배|금연|흡연"),
        ("alcohol", r"술|음주|금주"),
        ("diet_potassium", r"칼륨"),
        ("diet_sodium", r"국물|싱겁|짜게|소금|라면|젓갈|장아찌|간을"),
        ("diet_fat", r"튀김|삼겹살|기름진"),
        ("diet_carb_sugar", r"음료|탄산|주스|단 거|과자|커피믹스|콜라"),
        ("diet_pattern", r"채소|생선|잡곡"),
        ("stress", r"호흡|명상|스트레스"),
        ("activity_resistance", r"근력|밴드|의자에서 일어"),
        ("activity_sedentary_break", r"앉아 계|오래 앉"),
        ("weight", r"체중|몸무게"),
        ("activity_aerobic", r"걷|걸으|걸어|산책|운동"),
    )
)
_DIRECTIVE_CUE_RE = re.compile(r"(세요|시고요|하셔야|마시고|드시지|줄이|끊으|끊으셔야|해보세요|하십시오)")
_TARGET_HINT_RE = re.compile(r"(하루\s*\d+\s*(번|회|분|잔|개비)|주\s*\d+\s*(일|회|번)(\s*\d+\s*분)?|\d+\s*분)")
_REFUSED_RE = re.compile(r"(못\s*하|안\s*할|싫|못\s*끊)")
_HESITANT_RE = re.compile(r"(어렵|글쎄|자신(이)?\s*없|노력은|모르겠)")
_AGREED_RE = re.compile(r"(네|알겠|해볼게|할게|그럴게|그렇게\s*할)")
_BARRIER_RE = re.compile(r"(아파|아프|혼자|바빠|바쁘|회식|시간이\s*없|비가|추워|무릎|피곤|힘들|귀찮|배달)")


def _segment_transcript(transcript_text: str) -> list[dict[str, str]]:
    # Same seg_001 IDs as app.pipeline.segments (docs/stage1_output.md
    # section 6); imported lazily to keep providers free of a pipeline
    # import cycle at module load.
    from app.pipeline.segments import segments_from_transcript_text

    return segments_from_transcript_text(transcript_text)


def _directive_domain(text: str) -> Optional[str]:
    for domain, pattern in _DIRECTIVE_DOMAIN_PATTERNS:
        if pattern.search(text):
            return domain
    return None


def _span(seg: dict[str, str]) -> dict[str, Any]:
    return {
        "segment_id": seg["id"],
        "quote": seg["text"],
        "speaker": seg["speaker"],
        "role": seg["role"],
        "start": None,
        "end": None,
    }


def _agreement(text: str) -> str:
    if _REFUSED_RE.search(text):
        return "refused"
    if _HESITANT_RE.search(text):
        return "hesitant"
    if _AGREED_RE.search(text):
        return "agreed"
    return "unclear"


def _action_directives(segments: list[dict[str, str]]) -> list[dict[str, Any]]:
    """A doctor segment with a directive ending and a lifestyle keyword
    becomes a directive (whole segment copied verbatim); the patient/
    guardian segments up to the next doctor segment give the response and
    barriers. Medication sentences and questions are skipped."""
    directives: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        text = seg["text"]
        if seg["role"] != "doctor" or _QUESTION_RE.search(text) or _DOSE_UNIT_RE.search(text) or "약" in text:
            continue
        domain = _directive_domain(text)
        if domain is None or not _DIRECTIVE_CUE_RE.search(text):
            continue
        replies = []
        for nxt in segments[i + 1 :]:
            if nxt["role"] == "doctor":
                break
            if nxt["role"] in ("patient", "guardian"):
                replies.append(nxt)
        target = _TARGET_HINT_RE.search(text)
        directives.append(
            {
                "directive_id": f"AD-{len(directives) + 1}",
                "raw_text": text,
                "source_spans": [_span(seg)],
                "domain_hint": domain,
                "target_hint": target.group(0) if target else None,
                "patient_response": (
                    {"text": replies[0]["text"], "agreement": _agreement(replies[0]["text"]), "source_spans": [_span(replies[0])]}
                    if replies
                    else None
                ),
                "barrier_mentions": [
                    {"text": r["text"], "source_spans": [_span(r)]} for r in replies if _BARRIER_RE.search(r["text"])
                ],
                # The mock cannot judge ambiguity, so it never clears review.
                "needs_review": True,
            }
        )
    return directives


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
        if prompt_id == "classify_action_directive":
            return self._classify_action_directive(payload)
        raise ValueError(f"MockLLMProvider has no handler for prompt_id={prompt_id!r}")

    def _structure_transcript(self, payload: dict[str, Any]) -> dict[str, Any]:
        lines = [line.strip() for line in payload["transcript_text"].splitlines() if line.strip()]
        segments = payload.get("segments") or _segment_transcript(payload["transcript_text"])
        # Problem text stays the full transcript line (unchanged 0.1.0
        # behavior); IDs now come from the real segments when they line up.
        ids = [seg["id"] for seg in segments] if len(segments) == len(lines) else [f"seg_{i + 1:03d}" for i in range(len(lines))]
        problems = [
            {"text": line, "certainty": "stated", "source_segment_ids": [sid]}
            for line, sid in zip(lines, ids)
        ]
        return {
            "problems": problems,
            "tests": [],
            "medications": [],
            "plan": [],
            "warnings": [],
            "follow_up": [],
            "questions_or_conflicts": [],
            "action_directives": _action_directives(segments),
        }

    def _classify_action_directive(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Only reached when a directive has no usable domain_hint. The mock
        # has no basis to pick a catalog action, so it never guesses.
        return {"catalog_code": "custom", "confidence": 0.0, "rationale": "mock: no classification"}

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

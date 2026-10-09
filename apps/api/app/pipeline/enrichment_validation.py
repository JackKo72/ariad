"""Mechanical safety net for the clinical_enrichment stage
(tasks/04_CLINICAL_ENRICHMENT.md). Runs after every LLM (or mock) call,
regardless of provider -- the prompt asks the model to follow these rules,
but this module checks them structurally so a model mistake can't reach a
clinician unflagged. Pure function: no I/O, no provider/time dependency,
so it's fully unit-testable with synthetic segments/enrichment.
"""

from __future__ import annotations

import re

from app.domain.models import (
    ClinicalEnrichment,
    DiagnosisFinding,
    DiarizedSegment,
    ExamFinding,
    FollowUpQuestionSuggestion,
    MedicationFinding,
    SourceSpan,
)

_HAS_DIGIT_RE = re.compile(r"\d")
_NEGATED_STOP_RE = re.compile(r"(끊지|중단하지|멈추지)\s*(마세요|말고|말아)")


def _grounded_spans(spans: list[SourceSpan], segments_by_id: dict[str, DiarizedSegment]) -> list[SourceSpan]:
    """Keeps only spans whose quote is an actual substring of the segment
    it claims to come from -- the one check every finding type shares."""
    kept = []
    for span in spans:
        segment = segments_by_id.get(span.segment_id)
        if segment is not None and span.quote and span.quote in segment.text:
            kept.append(span)
    return kept


def validate_enrichment(
    enrichment: ClinicalEnrichment, segments: list[DiarizedSegment]
) -> ClinicalEnrichment:
    segments_by_id = {seg.id: seg for seg in segments}
    violations: list[str] = list(enrichment.validator_violations)

    def ground_or_drop(kind: str, item_id: str, spans: list[SourceSpan]) -> tuple[list[SourceSpan], bool]:
        grounded = _grounded_spans(spans, segments_by_id)
        if len(grounded) < len(spans):
            violations.append(f"{kind} {item_id}: ungrounded source_span dropped (quote not in segment text)")
        if not grounded:
            violations.append(f"{kind} {item_id}: dropped entirely (no grounded source_span)")
        return grounded, bool(grounded)

    medications: list[MedicationFinding] = []
    for item in enrichment.medications:
        spans, has_ground = ground_or_drop("medication", item.id, item.source_spans)
        if not has_ground:
            continue
        action, needs_review = item.action, item.needs_review
        if action == "stop" and any(_NEGATED_STOP_RE.search(s.quote) for s in spans):
            violations.append(
                f"medication {item.id}: source negates stopping but action=stop -- downgraded to unknown"
            )
            action, needs_review = "unknown", True
        # tasks/06_ASR_OUTPUT_VERIFICATION.md: real-hardware measurement
        # found ASR frequently drops/garbles dose numbers -- a dose
        # candidate is never auto-trusted regardless of which provider
        # (mock, OpenAI, or a future ASR-adjacent one) set needs_review.
        if item.dose_candidates:
            needs_review = True
        medications.append(item.model_copy(update={"source_spans": spans, "action": action, "needs_review": needs_review}))

    exam: list[ExamFinding] = []
    for item in enrichment.exam:
        spans, has_ground = ground_or_drop("exam", item.id, item.source_spans)
        if not has_ground:
            continue
        score_candidates, score_computable, value_candidates, needs_review = (
            item.score_candidates,
            item.score_computable,
            item.value_candidates,
            item.needs_review,
        )
        if score_candidates and not any(_HAS_DIGIT_RE.search(s.quote) for s in spans):
            violations.append(
                f"exam {item.id}: score_candidates without a verbatim number in source -- cleared"
            )
            score_candidates, score_computable, needs_review = [], False, True
        if value_candidates and not any(_HAS_DIGIT_RE.search(s.quote) for s in spans):
            violations.append(
                f"exam {item.id}: value_candidates without a verbatim number in source -- cleared"
            )
            value_candidates, needs_review = [], True
        # Same rule as medication dose above: any surviving numeric
        # observation (a graded score or a raw measurement like BP/weight/
        # glucose) is never auto-trusted, regardless of provider input.
        if score_candidates or value_candidates:
            needs_review = True
        exam.append(
            item.model_copy(
                update={
                    "source_spans": spans,
                    "score_candidates": score_candidates,
                    "score_computable": score_computable,
                    "value_candidates": value_candidates,
                    "needs_review": needs_review,
                }
            )
        )

    diagnoses: list[DiagnosisFinding] = []
    demoted_to_follow_up: list[FollowUpQuestionSuggestion] = []
    for item in enrichment.diagnoses:
        spans, has_ground = ground_or_drop("diagnosis", item.id, item.source_spans)
        if not has_ground:
            continue
        if not any(s.role == "doctor" for s in spans):
            violations.append(
                f"diagnosis {item.id}: no doctor-sourced span -- moved to follow_up_questions, not a diagnosis"
            )
            demoted_to_follow_up.append(
                FollowUpQuestionSuggestion(
                    id=f"demoted-{item.id}",
                    trigger_text=item.raw_text,
                    suggested_question=(
                        "환자/보호자 진술만으로는 진단을 확정할 수 없습니다. "
                        "의료진 확인이 필요합니다: " + item.raw_text
                    ),
                    rationale="원래 diagnosis로 분류되었으나 의사가 명시한 근거가 없어 강등됨",
                    needs_review=True,
                    source_spans=spans,
                )
            )
            continue
        diagnoses.append(item.model_copy(update={"source_spans": spans}))

    symptoms = []
    for item in enrichment.symptoms:
        spans, has_ground = ground_or_drop("symptom", item.id, item.source_spans)
        if not has_ground:
            continue
        symptoms.append(item.model_copy(update={"source_spans": spans}))

    plan = []
    for item in enrichment.plan:
        spans, has_ground = ground_or_drop("plan", item.id, item.source_spans)
        if not has_ground:
            continue
        plan.append(item.model_copy(update={"source_spans": spans}))

    follow_up_questions = []
    for item in enrichment.follow_up_questions:
        spans, has_ground = ground_or_drop("follow_up_question", item.id, item.source_spans)
        if not has_ground:
            continue
        follow_up_questions.append(item.model_copy(update={"source_spans": spans}))
    follow_up_questions.extend(demoted_to_follow_up)

    return enrichment.model_copy(
        update={
            "medications": medications,
            "symptoms": symptoms,
            "exam": exam,
            "diagnoses": diagnoses,
            "follow_up_questions": follow_up_questions,
            "plan": plan,
            "validator_violations": violations,
        }
    )

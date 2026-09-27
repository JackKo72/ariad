"""Unit: enrichment_validation.py is the mechanical safety net that runs
after every clinical_enrichment LLM (or mock) call -- these tests feed it
deliberately unsafe synthetic output (never something an actual provider
generated) to prove it catches and corrects what a prompt-only defense
can't guarantee (tasks/04_CLINICAL_ENRICHMENT.md)."""

from app.domain.models import (
    ClinicalEnrichment,
    DiagnosisFinding,
    DiarizedSegment,
    ExamFinding,
    MedicationFinding,
    SourceSpan,
    SymptomFinding,
)
from app.pipeline.enrichment_validation import validate_enrichment

_SEGMENTS = [
    DiarizedSegment(id="s1", speaker="A", role="doctor", start=0.0, end=2.0, text="다리 들어보세요"),
    DiarizedSegment(id="s3", speaker="B", role="patient", start=4.0, end=6.0, text="잠을 잘 못 자요."),
    DiarizedSegment(id="s4", speaker="A", role="doctor", start=6.0, end=8.0, text="약을 끊지 마세요."),
]


def _span(segment_id: str, quote: str, speaker: str, role: str) -> SourceSpan:
    return SourceSpan(segment_id=segment_id, quote=quote, speaker=speaker, role=role)


def test_ungrounded_quote_is_dropped_and_flagged():
    enrichment = ClinicalEnrichment(
        symptoms=[
            SymptomFinding(
                id="sym1",
                raw_text="잠을 잘 못 자요.",
                reported_by="patient",
                polarity="affirmed",
                source_spans=[_span("s3", "완전히 다른 말", "B", "patient")],
            )
        ]
    )
    fixed = validate_enrichment(enrichment, _SEGMENTS)
    assert fixed.symptoms == []  # no grounded evidence at all -> dropped entirely
    assert any("dropped entirely" in v for v in fixed.validator_violations)


def test_score_without_verbatim_number_is_cleared():
    enrichment = ClinicalEnrichment(
        exam=[
            ExamFinding(
                id="e1",
                raw_text="다리 들어보세요",
                kind="order",
                score_computable=True,
                score_candidates=[{"value": "mRS 2", "confidence": "low"}],
                source_spans=[_span("s1", "다리 들어보세요", "A", "doctor")],
            )
        ]
    )
    fixed = validate_enrichment(enrichment, _SEGMENTS)
    assert fixed.exam[0].score_computable is False
    assert fixed.exam[0].score_candidates == []
    assert any("score_candidates" in v for v in fixed.validator_violations)


def test_score_with_verbatim_number_in_source_is_kept():
    segments = _SEGMENTS + [
        DiarizedSegment(id="s5", speaker="A", role="doctor", start=8.0, end=10.0, text="mRS 2점입니다")
    ]
    enrichment = ClinicalEnrichment(
        exam=[
            ExamFinding(
                id="e2",
                raw_text="mRS 2점입니다",
                kind="observation",
                score_computable=True,
                score_candidates=[{"value": "mRS 2", "confidence": "high"}],
                source_spans=[_span("s5", "mRS 2점입니다", "A", "doctor")],
            )
        ]
    )
    fixed = validate_enrichment(enrichment, segments)
    assert fixed.exam[0].score_computable is True
    assert fixed.exam[0].score_candidates
    assert fixed.validator_violations == []


def test_diagnosis_without_doctor_source_is_demoted_to_follow_up_question():
    enrichment = ClinicalEnrichment(
        diagnoses=[
            DiagnosisFinding(
                id="d1",
                raw_text="잠을 잘 못 자요.",
                kind="confirmed",
                source_spans=[_span("s3", "잠을 잘 못 자요.", "B", "patient")],
            )
        ]
    )
    fixed = validate_enrichment(enrichment, _SEGMENTS)
    assert fixed.diagnoses == []
    assert len(fixed.follow_up_questions) == 1
    assert any("no doctor-sourced span" in v for v in fixed.validator_violations)


def test_diagnosis_with_doctor_source_is_kept():
    segments = _SEGMENTS + [
        DiarizedSegment(id="s6", speaker="A", role="doctor", start=10.0, end=12.0, text="편두통으로 진단됩니다")
    ]
    enrichment = ClinicalEnrichment(
        diagnoses=[
            DiagnosisFinding(
                id="d2",
                raw_text="편두통으로 진단됩니다",
                kind="confirmed",
                source_spans=[_span("s6", "편두통으로 진단됩니다", "A", "doctor")],
            )
        ]
    )
    fixed = validate_enrichment(enrichment, segments)
    assert len(fixed.diagnoses) == 1
    assert fixed.validator_violations == []


def test_medication_stop_contradicted_by_negated_stop_source_is_downgraded():
    enrichment = ClinicalEnrichment(
        medications=[
            MedicationFinding(
                id="m1",
                raw_text="약을 끊지 마세요.",
                action="stop",
                source_spans=[_span("s4", "약을 끊지 마세요.", "A", "doctor")],
            )
        ]
    )
    fixed = validate_enrichment(enrichment, _SEGMENTS)
    assert fixed.medications[0].action == "unknown"
    assert fixed.medications[0].needs_review is True
    assert any("downgraded to unknown" in v for v in fixed.validator_violations)


def test_medication_stop_with_genuine_stop_instruction_is_kept():
    segments = _SEGMENTS + [
        DiarizedSegment(id="s7", speaker="A", role="doctor", start=12.0, end=14.0, text="이 약은 이제 중단하세요.")
    ]
    enrichment = ClinicalEnrichment(
        medications=[
            MedicationFinding(
                id="m2",
                raw_text="이 약은 이제 중단하세요.",
                action="stop",
                source_spans=[_span("s7", "이 약은 이제 중단하세요.", "A", "doctor")],
            )
        ]
    )
    fixed = validate_enrichment(enrichment, segments)
    assert fixed.medications[0].action == "stop"
    assert fixed.validator_violations == []


def test_partially_grounded_item_keeps_only_grounded_spans():
    enrichment = ClinicalEnrichment(
        symptoms=[
            SymptomFinding(
                id="sym2",
                raw_text="잠을 잘 못 자요.",
                reported_by="patient",
                polarity="affirmed",
                source_spans=[
                    _span("s3", "잠을 잘 못 자요.", "B", "patient"),
                    _span("s3", "없는 문장", "B", "patient"),
                ],
            )
        ]
    )
    fixed = validate_enrichment(enrichment, _SEGMENTS)
    assert len(fixed.symptoms) == 1
    assert len(fixed.symptoms[0].source_spans) == 1
    assert any("ungrounded source_span dropped" in v for v in fixed.validator_violations)

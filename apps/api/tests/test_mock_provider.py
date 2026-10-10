"""Unit: MockLLMProvider must be deterministic and never invent content
(docs/CLAUDE.md medical/privacy rules)."""

from app.domain.models import DiarizedSegment
from app.pipeline.enrichment import enrich_clinical_findings
from app.pipeline.explanation import generate_patient_explanation
from app.pipeline.structure import structure_encounter
from app.providers.mock import MockLLMProvider

TRANSCRIPT = "의사: 혈압약 5mg 하루 한 번 복용하세요.\n환자: 네, 알겠습니다."

# tasks/04_CLINICAL_ENRICHMENT.md's four forbidden patterns, given as
# segments the way an audio-derived PipelineRun would carry them.
_FORBIDDEN_PATTERN_SEGMENTS = [
    DiarizedSegment(id="s1", speaker="A", role="doctor", start=0.0, end=2.0, text="다리 들어보세요"),
    DiarizedSegment(id="s2", speaker="A", role="doctor", start=2.0, end=4.0, text="다리를 끄나요?"),
    DiarizedSegment(
        id="s3",
        speaker="B",
        role="patient",
        start=4.0,
        end=8.0,
        text="잠을 잘 못 자요. 잠꼬대로 소리를 지르고 팔다리를 휘두른다고 하더라고요.",
    ),
    DiarizedSegment(id="s4", speaker="A", role="doctor", start=8.0, end=10.0, text="약을 끊지 마세요."),
]


def test_clinical_enrichment_is_deterministic():
    provider = MockLLMProvider()
    first = enrich_clinical_findings(_FORBIDDEN_PATTERN_SEGMENTS, provider)
    second = enrich_clinical_findings(_FORBIDDEN_PATTERN_SEGMENTS, provider)
    assert first == second


def test_clinical_enrichment_never_scores_a_bare_exam_order():
    """Forbidden pattern 1: "다리 들어보세요" alone must never produce an
    mRS/NIHSS/MRC score."""
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_FORBIDDEN_PATTERN_SEGMENTS, provider)
    assert enrichment.exam, "the exam order should still be captured"
    assert enrichment.exam[0].score_computable is False
    assert enrichment.exam[0].score_candidates == []


def test_clinical_enrichment_keeps_a_bare_question_as_a_question():
    """Forbidden pattern 2: "다리를 끄나요?" alone must never become an
    affirmed symptom or a diagnosis."""
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_FORBIDDEN_PATTERN_SEGMENTS, provider)
    questions = [s for s in enrichment.symptoms if s.reported_by == "doctor_question"]
    assert questions and questions[0].polarity == "question"
    assert enrichment.diagnoses == []


def test_clinical_enrichment_never_diagnoses_from_nocturnal_behavior_alone():
    """Forbidden pattern 3: specific nocturnal behavior (e.g. suggestive of
    RBD) without a doctor-stated diagnosis must surface only as a
    follow_up_questions suggestion, never as a diagnosis."""
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_FORBIDDEN_PATTERN_SEGMENTS, provider)
    assert enrichment.diagnoses == []
    assert any("잠꼬대" in q.trigger_text for q in enrichment.follow_up_questions)


def test_clinical_enrichment_does_not_flip_negated_stop_to_stop():
    """Forbidden pattern 4: "약을 끊지 마세요" must record action=continue,
    polarity=negated -- never action=stop."""
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_FORBIDDEN_PATTERN_SEGMENTS, provider)
    assert enrichment.medications
    assert enrichment.medications[0].action == "continue"
    assert enrichment.medications[0].polarity == "negated"


def test_clinical_enrichment_source_spans_are_grounded_in_segment_text():
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_FORBIDDEN_PATTERN_SEGMENTS, provider)
    segments_by_id = {seg.id: seg.text for seg in _FORBIDDEN_PATTERN_SEGMENTS}
    all_findings = (
        enrichment.medications
        + enrichment.symptoms
        + enrichment.exam
        + enrichment.diagnoses
        + enrichment.plan
        + enrichment.follow_up_questions
    )
    assert all_findings, "sanity check: the fixture should have produced at least one finding"
    for finding in all_findings:
        assert finding.source_spans, f"{finding.id} must have at least one source_span"
        for span in finding.source_spans:
            assert span.quote in segments_by_id[span.segment_id]
    assert enrichment.validator_violations == []


# tasks/06_ASR_OUTPUT_VERIFICATION.md: vital-sign (BP/weight/glucose/
# pulse/temperature) reading detection rules added to the mock provider.
_VITAL_SIGN_SEGMENTS = [
    DiarizedSegment(
        id="v1", speaker="A", role="doctor", start=0.0, end=3.0,
        text="혈압을 재보니 138에 86으로 나왔습니다.",
    ),
    DiarizedSegment(
        id="v2", speaker="A", role="doctor", start=3.0, end=5.0,
        text="혈압을 재볼까요?",
    ),
    DiarizedSegment(
        id="v3", speaker="A", role="doctor", start=5.0, end=8.0,
        text="오늘은 혈압이 백삼십이에 팔십사, 맥박은 칠십회였습니다.",
    ),
    DiarizedSegment(
        id="v4", speaker="A", role="doctor", start=8.0, end=10.0,
        text="체중을 확인해보니 72킬로그램이네요.",
    ),
]


def test_vital_sign_reading_with_number_becomes_an_observation_candidate():
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_VITAL_SIGN_SEGMENTS, provider)
    bp_findings = [e for e in enrichment.exam if e.raw_text.startswith("혈압을 재보니")]
    assert len(bp_findings) == 1
    finding = bp_findings[0]
    assert finding.kind == "observation"
    assert finding.value_candidates
    assert finding.value_candidates[0].value == "혈압을 재보니 138에 86으로 나왔습니다."
    assert finding.needs_review is True


def test_vital_sign_keyword_alone_becomes_an_order_with_no_value_candidate():
    """A vital-sign keyword with no number (an order/question) must never
    produce a value_candidate -- the mock never guesses a reading that
    wasn't actually stated."""
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_VITAL_SIGN_SEGMENTS, provider)
    order_findings = [e for e in enrichment.exam if e.raw_text == "혈압을 재볼까요?"]
    assert len(order_findings) == 1
    assert order_findings[0].kind == "order"
    assert order_findings[0].value_candidates == []


def test_two_vital_signs_in_one_sentence_gets_low_confidence_not_a_guess():
    """tasks/06's "ownership ambiguity" case (which number belongs to
    which keyword) -- the mock still reports the candidate (so a
    clinician can look) but never pairs a specific number to a specific
    keyword, and flags it at low confidence."""
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_VITAL_SIGN_SEGMENTS, provider)
    combined_findings = [e for e in enrichment.exam if e.raw_text.startswith("오늘은 혈압이")]
    assert len(combined_findings) == 1
    finding = combined_findings[0]
    assert finding.value_candidates[0].confidence == "low"
    assert {c.value for c in finding.test_name_candidates} == {"혈압", "맥박"}


def test_vital_sign_reading_recognized_even_when_number_is_hangul_words():
    """Real ASR output often renders a spoken number as Hangul syllables,
    not digits -- the detection rule must not be digit-only."""
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_VITAL_SIGN_SEGMENTS, provider)
    combined_findings = [e for e in enrichment.exam if e.raw_text.startswith("오늘은 혈압이")]
    assert combined_findings and combined_findings[0].kind == "observation"


def test_vital_sign_with_trailing_unit_word_becomes_an_observation():
    provider = MockLLMProvider()
    enrichment = enrich_clinical_findings(_VITAL_SIGN_SEGMENTS, provider)
    weight_findings = [e for e in enrichment.exam if e.raw_text.startswith("체중을")]
    assert len(weight_findings) == 1
    assert weight_findings[0].kind == "observation"
    assert weight_findings[0].value_candidates


def test_structure_is_deterministic():
    provider = MockLLMProvider()
    first = structure_encounter(TRANSCRIPT, provider)
    second = structure_encounter(TRANSCRIPT, provider)
    assert first == second


def test_structure_only_copies_transcript_text_verbatim():
    provider = MockLLMProvider()
    structure = structure_encounter(TRANSCRIPT, provider)
    for problem in structure.problems:
        assert problem.text in TRANSCRIPT


def test_explanation_is_deterministic_given_same_structure():
    provider = MockLLMProvider()
    structure = structure_encounter(TRANSCRIPT, provider)
    first = generate_patient_explanation(structure, provider)
    second = generate_patient_explanation(structure, provider)
    assert first == second


def test_explanation_current_situation_traces_to_source_segments():
    provider = MockLLMProvider()
    structure = structure_encounter(TRANSCRIPT, provider)
    explanation = generate_patient_explanation(structure, provider)
    assert len(explanation.current_situation) == len(structure.problems)
    all_source_ids = {sid for p in structure.problems for sid in p.source_segment_ids}
    mapped_ids = {sid for m in explanation.source_map for sid in m.source_segment_ids}
    assert mapped_ids == all_source_ids


def test_empty_transcript_yields_empty_structure():
    provider = MockLLMProvider()
    structure = structure_encounter("", provider)
    assert structure.problems == []

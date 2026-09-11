"""Unit: MockLLMProvider must be deterministic and never invent content
(docs/CLAUDE.md medical/privacy rules)."""

from app.pipeline.explanation import generate_patient_explanation
from app.pipeline.structure import structure_encounter
from app.providers.mock import MockLLMProvider

TRANSCRIPT = "의사: 혈압약 5mg 하루 한 번 복용하세요.\n환자: 네, 알겠습니다."


def test_structure_is_deterministic():
    provider = MockLLMProvider()
    first = structure_encounter(TRANSCRIPT, provider)
    second = structure_encounter(TRANSCRIPT, provider)
    assert first == second


def test_structure_only_copies_transcript_text_verbatim():
    provider = MockLLMProvider()
    structure = structure_encounter(TRANSCRIPT, provider)
    for problem in structure.problems:
        assert problem["text"] in TRANSCRIPT


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
    all_source_ids = {sid for p in structure.problems for sid in p["source_segment_ids"]}
    mapped_ids = {sid for m in explanation.source_map for sid in m["source_segment_ids"]}
    assert mapped_ids == all_source_ids


def test_empty_transcript_yields_empty_structure():
    provider = MockLLMProvider()
    structure = structure_encounter("", provider)
    assert structure.problems == []

"""Unit: clinical frames, term-candidate validation, review checklist
(tasks/10_CLINICAL_FRAME_AND_REVIEW.md). Synthetic text only."""

import json
import typing

import pytest

from app.domain.models import ClinicalFrameId, ClinicalStructure, Decision, Medication, TermCandidate
from app.pipeline.explanation import generate_patient_explanation
from app.pipeline.frames import FRAMES_DIR, load_frame, validate_term_candidates
from app.pipeline.review_checklist import build_review_checklist, missing_acknowledgments
from app.pipeline.structure import structure_encounter
from app.providers.mock import MockLLMProvider

TRANSCRIPT = "의사: 막힌 혈관을 뚫는 시술은 지금은 안 하겠습니다.\n의사: 제 말을 따라 해 보세요."
EVT = "EVT (endovascular thrombectomy)"


def _candidate(**overrides) -> TermCandidate:
    fields = {"spoken_text": "막힌 혈관을 뚫는 시술", "term": EVT, "frame": "stroke", "source_segment_ids": ["seg-1"]}
    return TermCandidate(**{**fields, **overrides})


FRAME_IDS = sorted(typing.get_args(ClinicalFrameId))


@pytest.mark.parametrize("frame_id", FRAME_IDS)
def test_frame_files_load_with_unique_terms_and_shared_exam(frame_id):
    frame = load_frame(frame_id)
    terms = [t["term"] for t in frame["terms"]]
    assert frame["id"] == frame_id and len(terms) == len(set(terms))
    assert all(t["spoken_examples"] for t in frame["terms"])
    assert "diplopia (복시)" in terms and "tandem gait (일자 보행)" in terms  # shared neuro exam merged in
    assert "hematuria (혈뇨)" in terms and "increased sputum (객담 증가)" in terms  # shared ICU/medicine
    assert {t["risk"] for t in frame["terms"]} <= {"exam", "inference"}
    assert all("risk" in t for t in frame["terms"])
    assert "includes" not in frame and "note" not in frame  # LLM gets the merged vocabulary only


def test_frame_ids_match_files():
    assert sorted(p.stem for p in FRAMES_DIR.glob("*.json")) == FRAME_IDS


def test_shared_exam_term_is_valid_in_any_frame():
    transcript = "의사: 이거 두 개로 보여요?"
    structure = ClinicalStructure(term_candidates=[
        TermCandidate(spoken_text="두 개로 보여요", term="diplopia (복시)", frame="headache")])
    assert len(validate_term_candidates(structure, "headache", transcript).term_candidates) == 1


def test_valid_candidate_is_kept():
    structure = ClinicalStructure(term_candidates=[_candidate()])
    assert validate_term_candidates(structure, "stroke", TRANSCRIPT).term_candidates == [_candidate()]


@pytest.mark.parametrize(
    "frame_selected, overrides",
    [
        (None, {}),                                  # no frame selected at all
        ("seizure", {}),                             # candidate's frame not the selected one
        ("stroke", {"term": "tPA"}),                 # term outside the vocabulary
        ("stroke", {"spoken_text": "혈전용해제를 주겠습니다"}),  # quote not in the transcript
        ("stroke", {"spoken_text": "  "}),           # empty quote
    ],
)
def test_invalid_candidates_are_dropped(frame_selected, overrides):
    structure = ClinicalStructure(term_candidates=[_candidate(**overrides)])
    assert validate_term_candidates(structure, frame_selected, TRANSCRIPT).term_candidates == []


def test_spacing_differences_in_quote_are_tolerated():
    structure = ClinicalStructure(term_candidates=[_candidate(spoken_text="막힌혈관을 뚫는  시술")])
    assert len(validate_term_candidates(structure, "stroke", TRANSCRIPT).term_candidates) == 1


class RecordingProvider:
    """Returns a fixed response and records every payload it was sent."""

    def __init__(self, response: dict):
        self.response = response
        self.payloads: list[tuple[str, dict]] = []

    def generate_json(self, prompt_id, payload, stage_timer=None):
        self.payloads.append((prompt_id, json.loads(json.dumps(payload, ensure_ascii=False))))
        return self.response


def test_structure_sends_frame_only_when_selected_and_filters_output():
    mock_output = MockLLMProvider().generate_json("structure_transcript", {"transcript_text": TRANSCRIPT})
    response = {**mock_output, "term_candidates": [_candidate().model_dump(), _candidate(term="tPA").model_dump()]}

    provider = RecordingProvider(response)
    with_frame = structure_encounter(TRANSCRIPT, provider, clinical_frame="stroke")
    assert provider.payloads[0][1]["clinical_frame"]["id"] == "stroke"
    assert [c.term for c in with_frame.term_candidates] == [EVT]

    provider = RecordingProvider(response)
    without = structure_encounter(TRANSCRIPT, provider)
    assert "clinical_frame" not in provider.payloads[0][1]
    assert without.term_candidates == []


def test_patient_explanation_never_sees_term_candidates():
    explanation = MockLLMProvider().generate_json(
        "patient_explanation", {"structure": ClinicalStructure().model_dump()}
    )
    provider = RecordingProvider(explanation)
    generate_patient_explanation(ClinicalStructure(term_candidates=[_candidate()]), provider)
    assert provider.payloads[0][1]["structure"]["term_candidates"] == []


def _decision(status: str, **overrides) -> Decision:
    return Decision(**{"text": "EVT", "status": status, "source_segment_ids": ["seg-1"], **overrides})


def test_checklist_lists_risky_items_only():
    structure = ClinicalStructure(
        decisions=[_decision("decided_to_do"), _decision("decided_not_to_do"),
                   _decision("conditional", condition="많이 나빠지면"), _decision("decided_to_do", needs_confirmation=True)],
        term_candidates=[_candidate()],
        medications=[Medication(name="A", dose="", route="", frequency="", action="start"),
                     Medication(name="B", dose="", route="", frequency="", action="stop", needs_confirmation=True)],
    )
    items = build_review_checklist(structure)
    assert [i.kind for i in items] == ["decision", "decision", "decision", "term_candidate", "medication"]
    assert items[0].text.startswith("[하지 않음]")
    assert "조건: 많이 나빠지면" in items[1].text


def test_editing_an_item_invalidates_its_acknowledgment():
    before = ClinicalStructure(decisions=[_decision("decided_not_to_do")])
    ack = [i.id for i in build_review_checklist(before)]
    assert missing_acknowledgments(before, ack) == []
    flipped = ClinicalStructure(decisions=[_decision("decided_to_do", needs_confirmation=True)])
    assert len(missing_acknowledgments(flipped, ack)) == 1


def test_validator_sets_risk_from_vocabulary_not_from_llm():
    transcript = "의사: 막힌 혈관을 뚫는 시술은 안 합니다. 손을 쥐어 보세요."
    structure = ClinicalStructure(term_candidates=[
        _candidate(risk="exam"),  # LLM claims "exam" for EVT -- vocabulary says inference
        TermCandidate(spoken_text="손을 쥐어 보세요", term="motor strength test (근력 검사)", frame="stroke",
                      risk="inference"),
    ])
    kept = validate_term_candidates(structure, "stroke", transcript).term_candidates
    assert [(c.term, c.risk) for c in kept] == [(EVT, "inference"), ("motor strength test (근력 검사)", "exam")]


def test_checklist_requires_only_inference_term_candidates():
    structure = ClinicalStructure(term_candidates=[
        _candidate(risk="inference"),
        TermCandidate(spoken_text="손을 쥐어 보세요", term="motor strength test (근력 검사)", frame="stroke", risk="exam"),
    ])
    assert [i.text for i in build_review_checklist(structure)] == [
        '"막힌 혈관을 뚫는 시술" → EVT (endovascular thrombectomy) (용어 후보, stroke)']


def test_every_inference_term_is_explicitly_marked():
    # "의심" in a term name means a suspected diagnosis -- must never be an exam record.
    for frame_id in FRAME_IDS:
        for term in load_frame(frame_id)["terms"]:
            if "의심" in term["term"]:
                assert term["risk"] == "inference", term["term"]

"""Unit: tasks/14 disease must-check lists (app.pipeline.frame_checks).
Synthetic text only."""

import json

import pytest

from app.domain.models import FrameCheckItem
from app.pipeline.explanation import generate_patient_explanation
from app.pipeline.frame_checks import CHECKS_DIR, load_frame_checks, validate_frame_checks
from app.pipeline.frames import FRAMES_DIR
from app.pipeline.structure import PROMPT_VERSION, structure_encounter

TRANSCRIPT = "보호자: 아침 일곱 시까지는 괜찮으셨어요\n의사: 사진에서 피가 난 곳은 없어요"
CHECKLIST = {"frame": "stroke", "items": [
    {"id": "onset_time", "label": "증상 시작 시각", "look_for": "언제"},
    {"id": "hemorrhage", "label": "뇌출혈 여부", "look_for": "출혈"},
    {"id": "swallow", "label": "삼킴 평가", "look_for": "삼킴"},
]}


class Provider:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def generate_json(self, prompt_id, payload, stage_timer=None):
        self.calls.append((prompt_id, json.loads(json.dumps(payload, ensure_ascii=False))))
        return self.responses[prompt_id]


def test_result_is_the_whole_list_in_order_with_labels_from_the_file():
    found = [FrameCheckItem(id="hemorrhage", label="(LLM label)", status="mentioned", spoken_text="피가 난 곳은 없어요"),
             FrameCheckItem(id="made_up", status="mentioned", spoken_text="괜찮으셨어요")]
    result = validate_frame_checks(found, CHECKLIST, TRANSCRIPT)
    assert [(c.id, c.label, c.status) for c in result] == [
        ("onset_time", "증상 시작 시각", "not_mentioned"),  # missing from the LLM -> not_mentioned
        ("hemorrhage", "뇌출혈 여부", "mentioned"),
        ("swallow", "삼킴 평가", "not_mentioned"),
    ]


def test_mentioned_without_a_verbatim_quote_is_not_mentioned():
    found = [FrameCheckItem(id="onset_time", status="mentioned", spoken_text="오전 7시 발병"),  # paraphrase
             FrameCheckItem(id="hemorrhage", status="mentioned", spoken_text="")]
    result = validate_frame_checks(found, CHECKLIST, TRANSCRIPT)
    assert [c.status for c in result[:2]] == ["not_mentioned", "not_mentioned"]
    assert result[0].spoken_text == ""


def test_not_mentioned_quote_is_cleared():
    found = [FrameCheckItem(id="swallow", status="not_mentioned", spoken_text="괜찮으셨어요")]
    assert validate_frame_checks(found, CHECKLIST, TRANSCRIPT)[2].spoken_text == ""


@pytest.mark.parametrize("frame", ["stroke", "seizure", "movement", "cognitive", "spine"])
def test_draft_lists_exist_for_the_requested_frames(frame):
    checks = load_frame_checks(frame)
    ids = [i["id"] for i in checks["items"]]
    assert checks["frame"] == frame and len(ids) == len(set(ids)) >= 10
    assert all(i["label"] and i["look_for"] for i in checks["items"])


def test_every_check_file_names_an_existing_frame():
    for path in CHECKS_DIR.glob("*.json"):
        assert (FRAMES_DIR / path.name).is_file(), path.name


def test_frame_without_a_list_makes_no_call():
    assert load_frame_checks("headache") is None
    provider = Provider({"structure_transcript": {}, "coverage_check": {},
                         "term_candidates": {"term_candidates": []}})
    result = structure_encounter(TRANSCRIPT, provider, clinical_frame="headache")
    assert "frame_checklist" not in [pid for pid, _ in provider.calls]
    assert result.frame_checks == []


def test_structure_gets_the_checks_and_patient_text_never_sees_them():
    provider = Provider({
        "structure_transcript": {"frame_checks": [{"id": "x", "status": "mentioned"}]},  # discarded
        "coverage_check": {},
        "term_candidates": {"term_candidates": []},
        "frame_checklist": {"items": [{"id": "onset_time", "status": "mentioned",
                                       "spoken_text": "아침 일곱 시까지는 괜찮으셨어요"}]},
    })
    result = structure_encounter(TRANSCRIPT, provider, clinical_frame="stroke")
    sent = dict(provider.calls)["frame_checklist"]
    assert sent["checklist"]["frame"] == "stroke" and "note" not in sent["checklist"]
    assert result.frame_checks[0].id == "onset_time" and result.frame_checks[0].status == "mentioned"
    assert {c.id for c in result.frame_checks} == {i["id"] for i in load_frame_checks("stroke")["items"]}
    assert "frame_checks" not in dict(provider.calls)["coverage_check"]["structure"]

    explain = Provider({"patient_explanation": {"draft_notice": "초안"}})
    generate_patient_explanation(result, explain)
    assert explain.calls[0][1]["structure"]["frame_checks"] == []


def test_prompt_version_records_the_checklist_prompt():
    assert "frame_checklist@" in PROMPT_VERSION

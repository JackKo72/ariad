"""Step 3 stage-1 extension: segments -> structure LLM -> grounded
action_directives (docs/stage1_output.md sections 6-8). Synthetic data only."""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from app.domain.models import ActionDirective, DiarizedSegment, PipelineRun, SourceSpan
from app.pipeline.directive_validation import directive_issues, validate_action_directives
from app.pipeline.explanation import generate_patient_explanation
from app.pipeline.segments import segments_from_pipeline_run, segments_from_transcript_text
from app.pipeline.structure import structure_encounter
from app.providers.mock import MockLLMProvider
from app.stage2.catalog import load_catalog

REPO_ROOT = Path(__file__).resolve().parents[3]
TRANSCRIPT = "의사: 국물은 이제 드시지 마시고요.\n환자: 그게 제일 어렵네요. 혼자 살아서 라면을 자주 먹어요.\n의사: 주 5일 30분 걸으세요.\n환자: 네, 해볼게요."
SEGMENTS = segments_from_transcript_text(TRANSCRIPT)


class _SpyProvider:
    """Records payloads and replays scripted structure outputs."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls: list[tuple[str, dict]] = []

    def generate_json(self, prompt_id, payload, stage_timer=None):
        self.calls.append((prompt_id, payload))
        return self.outputs.pop(0) if self.outputs else {}


def _span(seg, quote=None, **overrides):
    data = {"segment_id": seg["id"], "quote": quote or seg["text"], "speaker": seg["speaker"], "role": seg["role"]}
    data.update(overrides)
    return SourceSpan(**data)


def _grounded_directive(**overrides) -> ActionDirective:
    data = dict(
        directive_id="AD-1",
        raw_text="국물은 이제 드시지 마시고요.",
        source_spans=[_span(SEGMENTS[0])],
        patient_response={"text": "그게 제일 어렵네요.", "agreement": "hesitant", "source_spans": [_span(SEGMENTS[1], "그게 제일 어렵네요.")]},
        needs_review=False,
    )
    data.update(overrides)
    return ActionDirective(**data)


# ---------------------------------------------------------------- segments


def test_manual_text_gets_seg_ids_speaker_and_role_from_prefix():
    segs = segments_from_transcript_text("의사: 걸으세요.\n\n보호자: 네.\n메모 한 줄")
    assert segs == [
        {"id": "seg_001", "speaker": "의사", "role": "doctor", "text": "걸으세요."},
        {"id": "seg_002", "speaker": "보호자", "role": "guardian", "text": "네."},
        {"id": "seg_003", "speaker": "", "role": "unknown", "text": "메모 한 줄"},
    ]


def test_pipeline_run_keeps_real_ids_speaker_and_confirmed_role():
    run = PipelineRun(
        id="r", encounter_id="e", mode="manual", status="needs_role_confirmation",
        segments=[
            DiarizedSegment(id="seg_007", speaker="B", start=5.0, end=6.0, text="네."),
            DiarizedSegment(id="seg_003", speaker="A", start=1.0, end=2.0, text="걸으세요."),
        ],
        roles={"A": "doctor", "B": "patient"}, created_at="t", updated_at="t",
    )
    assert segments_from_pipeline_run(run) == [
        {"id": "seg_003", "speaker": "A", "role": "doctor", "text": "걸으세요."},
        {"id": "seg_007", "speaker": "B", "role": "patient", "text": "네."},
    ]


# ---------------------------------------------------------------- grounding validation


def test_grounded_directive_keeps_llm_needs_review_value():
    assert directive_issues(_grounded_directive(), SEGMENTS) == []
    assert validate_action_directives([_grounded_directive()], SEGMENTS)[0].needs_review is False


@pytest.mark.parametrize(
    "overrides, expected_issue",
    [
        ({"source_spans": []}, "no source_spans"),
        ({"source_spans": [_span(SEGMENTS[0], segment_id="seg_099")]}, "unknown segment_id"),
        ({"source_spans": [_span(SEGMENTS[0], quote="국물 금지")]}, "quote not in"),
        ({"source_spans": [_span(SEGMENTS[0], role="patient")]}, "speaker/role tag differs"),
        ({"source_spans": [_span(SEGMENTS[0], speaker="A")]}, "speaker/role tag differs"),
        ({"source_spans": [_span(SEGMENTS[1])], "raw_text": "그게 제일 어렵네요."}, "not in ['doctor']"),
        ({"raw_text": "국물을 드시지 마세요."}, "raw_text not verbatim"),
        ({"target_hint": "주 7일"}, "target_hint number"),
        (
            {"patient_response": {"text": "국물은 이제 드시지 마시고요.", "agreement": "agreed", "source_spans": [_span(SEGMENTS[0])]}},
            "patient_response",
        ),
        ({"barrier_mentions": [{"text": "혼자 살아서", "source_spans": []}]}, "barrier_mentions[0]: no source_spans"),
    ],
)
def test_ungrounded_directive_is_forced_to_review(overrides, expected_issue):
    directive = _grounded_directive(**overrides)
    issues = directive_issues(directive, SEGMENTS)
    assert any(expected_issue in i for i in issues), issues
    assert validate_action_directives([directive], SEGMENTS)[0].needs_review is True


def test_issue_strings_never_contain_transcript_text():
    directive = _grounded_directive(raw_text="국물을 드시지 마세요.", source_spans=[_span(SEGMENTS[0], quote="없는 인용")])
    for issue in directive_issues(directive, SEGMENTS):
        assert "국물" not in issue and "인용" not in issue


# ---------------------------------------------------------------- structure stage


def test_structure_payload_carries_segments():
    spy = _SpyProvider([{}])
    structure_encounter(TRANSCRIPT, spy)
    prompt_id, payload = spy.calls[0]
    assert prompt_id == "structure_transcript"
    assert payload["transcript_text"] == TRANSCRIPT
    assert [s["id"] for s in payload["segments"]] == ["seg_001", "seg_002", "seg_003", "seg_004"]


def test_structure_uses_given_segments_when_provided():
    segs = [{"id": "seg_042", "speaker": "A", "role": "doctor", "text": "걸으세요."}]
    spy = _SpyProvider([{}])
    structure_encounter("의사: 걸으세요.", spy, segments=segs)
    assert spy.calls[0][1]["segments"] == segs


def test_structure_retries_invalid_output_once():
    spy = _SpyProvider([{"problems": "not-a-list"}, {}])
    structure = structure_encounter(TRANSCRIPT, spy)
    assert len(spy.calls) == 2 and structure.problems == []


def test_structure_fails_after_second_invalid_output():
    spy = _SpyProvider([{"problems": "x"}, {"problems": "x"}])
    with pytest.raises(ValidationError):
        structure_encounter(TRANSCRIPT, spy)
    assert len(spy.calls) == 2


def test_structure_applies_grounding_check_to_llm_directives():
    fabricated = _grounded_directive(source_spans=[_span(SEGMENTS[0], segment_id="U-42")]).model_dump()
    structure = structure_encounter(TRANSCRIPT, _SpyProvider([{"action_directives": [fabricated]}]))
    assert structure.action_directives[0].needs_review is True


def test_explanation_payload_excludes_action_directives():
    structure = structure_encounter(TRANSCRIPT, MockLLMProvider())
    assert structure.action_directives  # precondition: there is something to leak
    spy = _SpyProvider([{}])
    generate_patient_explanation(structure, spy)
    sent = spy.calls[0][1]["structure"]
    assert "action_directives" not in sent
    assert set(sent) == {"problems", "tests", "medications", "plan", "warnings", "follow_up", "questions_or_conflicts"}


# ---------------------------------------------------------------- mock provider


def test_mock_directives_are_grounded_and_tagged():
    structure = structure_encounter(TRANSCRIPT, MockLLMProvider())
    assert [d.domain_hint for d in structure.action_directives] == ["diet_sodium", "activity_aerobic"]
    for d in structure.action_directives:
        assert directive_issues(d, SEGMENTS) == []
        assert d.needs_review is True  # mock never clears review
    first = structure.action_directives[0]
    assert (first.source_spans[0].segment_id, first.source_spans[0].role) == ("seg_001", "doctor")
    assert first.patient_response.agreement.value == "hesitant"
    assert first.barrier_mentions[0].source_spans[0].segment_id == "seg_002"
    assert structure.action_directives[1].target_hint == "주 5일 30분"


def test_mock_skips_questions_and_medication_orders():
    text = "의사: 담배는 지금도 피우세요?\n환자: 네.\n의사: 혈압약 5mg 드세요.\n환자: 네."
    assert structure_encounter(text, MockLLMProvider()).action_directives == []


def test_mock_problem_ids_use_seg_format():
    structure = structure_encounter(TRANSCRIPT, MockLLMProvider())
    assert [p.source_segment_ids for p in structure.problems] == [["seg_001"], ["seg_002"], ["seg_003"], ["seg_004"]]


# ---------------------------------------------------------------- contracts / prompt


def test_mock_output_with_directives_matches_contract_schema():
    schema = json.loads((REPO_ROOT / "packages/contracts/schema/clinical_structure.schema.json").read_text())
    output = MockLLMProvider().generate_json("structure_transcript", {"transcript_text": TRANSCRIPT, "segments": SEGMENTS})
    assert output["action_directives"]
    jsonschema.validate(output, schema)


def test_contract_schema_still_accepts_pre_stage2_output():
    schema = json.loads((REPO_ROOT / "packages/contracts/schema/clinical_structure.schema.json").read_text())
    old = json.loads((REPO_ROOT / "tests/fixtures/audio/sample_consultation.structure.json").read_text())
    assert "action_directives" not in old
    jsonschema.validate(old, schema)


def test_prompt_lists_exactly_the_catalog_domains():
    prompt = (REPO_ROOT / "prompts/structure_transcript.md").read_text(encoding="utf-8")
    section = prompt.split("`domain_hint`", 1)[1].split("`target_hint`", 1)[0]
    listed = set(re.findall(r"`([a-z_]+)`", section)) - {"null"}
    assert listed == {a.domain for a in load_catalog().actions}


def test_prompt_keeps_every_0_1_0_rule_line():
    """기존 프롬프트는 유지: every rule bullet of 0.1.0 is still present."""
    prompt = (REPO_ROOT / "prompts/structure_transcript.md").read_text(encoding="utf-8")
    for line in (
        "- 입력에 없는 사실을 추가하지 않는다.",
        "- 부정, 불확실성, 과거력, 현재 계획을 구분한다.",
        "- 약명, 용량, 단위, 횟수, 날짜, 수치는 원문 그대로 보존한다.",
        "- 서로 모순되면 하나를 선택하지 말고 conflict로 표시한다.",
        "- 불명확하면 추측하지 말고 `needs_confirmation=true`로 둔다.",
        "- 각 중요 사실에 근거 segment ID를 연결한다.",
    ):
        assert line in prompt

"""Unit: tasks/13-e coverage call (app.pipeline.structure.add_missed_facts).
Synthetic text only."""

import json

from app.domain.models import ClinicalStructure
from app.pipeline.structure import PROMPT_VERSION, add_missed_facts, structure_encounter

TRANSCRIPT = "의사: 오늘 피 검사가 안 좋게 나왔어요\n의사: 내일 다시 볼게요"


class Provider:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def generate_json(self, prompt_id, payload, stage_timer=None):
        self.calls.append((prompt_id, json.loads(json.dumps(payload, ensure_ascii=False))))
        return self.responses[prompt_id]


def test_missed_items_are_appended_after_the_structure_items():
    first = {"plan": [{"text": "내일 다시 봄", "source_segment_ids": ["seg_2"]}]}
    missed = {"findings": [{"test_or_exam": "피 검사", "result": "안 좋게 나옴", "interpretation": "",
                            "source_segment_ids": ["seg_1"], "needs_confirmation": False}],
              "plan": [{"text": "외래 예약", "source_segment_ids": ["seg_2"]}]}
    provider = Provider({"structure_transcript": first, "coverage_check": missed})

    result = structure_encounter(TRANSCRIPT, provider)

    assert [pid for pid, _ in provider.calls] == ["structure_transcript", "coverage_check"]
    sent = provider.calls[1][1]
    assert sent["transcript_text"] == TRANSCRIPT and sent["structure"]["plan"][0]["text"] == "내일 다시 봄"
    assert "term_candidates" not in sent["structure"]
    assert [p.text for p in result.plan] == ["내일 다시 봄", "외래 예약"]
    assert result.findings[0].result == "안 좋게 나옴"


def test_exact_repeats_are_dropped_and_term_candidates_ignored():
    structure = ClinicalStructure.model_validate({"plan": [{"text": "내일 다시 봄"}],
                                                  "questions_or_conflicts": ["시간 불명확"]})
    missed = {"plan": [{"text": "내일  다시 봄", "source_segment_ids": ["seg_9"]}],
              "questions_or_conflicts": ["시간 불명확"],
              "term_candidates": [{"spoken_text": "피 검사", "term": "CBC", "frame": "stroke"}]}
    result = add_missed_facts(TRANSCRIPT, structure, Provider({"coverage_check": missed}))
    assert [p.text for p in result.plan] == ["내일 다시 봄"]
    assert result.questions_or_conflicts == ["시간 불명확"]
    assert result.term_candidates == []


def test_nothing_missed_leaves_the_structure_unchanged():
    structure = ClinicalStructure.model_validate({"plan": [{"text": "내일 다시 봄"}]})
    assert add_missed_facts(TRANSCRIPT, structure, Provider({"coverage_check": {}})) == structure


def test_prompt_version_records_the_coverage_prompt():
    assert "coverage_check@" in PROMPT_VERSION

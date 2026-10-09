"""Unit: app.eval.structure_eval and scripts/answer_to_transcript.py
(tasks/09_STRUCTURE_EVAL_AGAINST_CLINICIAN_GOLD.md). Synthetic text only."""

from pathlib import Path

import pytest

from app.eval.structure_eval import matches, score_structure

GOLD = {
    "items": [
        {"id": "dialysis_possible", "tier": "conversation", "must_match": [["투석"], ["할수도", "가능"]]},
        {"id": "life_sustaining", "tier": "conversation", "must_match": [["연명"]]},
        {"id": "ctx_drug", "tier": "context_only", "must_match": [["midazolam", "미다졸람"]]},
        {"id": "ctx_cin", "tier": "context_only", "must_match": [["cin"]]},
    ]
}
INPUT = "의사: 투석을 해야 할 수도 있어요\n의사: 연명의료 상의가 필요합니다"


def test_korean_ignores_spacing_ascii_needs_whole_word():
    assert matches("투석을 해야 할 수도", [["투석"], ["할수도"]])
    assert not matches("continue current medicine", [["cin"]])
    assert matches("r/o CIN", [["cin"]])


def test_one_output_item_must_satisfy_all_groups():
    # "투석" and "가능" in two different items is not a match.
    output = {"plan": [{"text": "투석"}, {"text": "가능성 있음"}]}
    result = score_structure(output, GOLD, INPUT).items[0]
    assert result.hit is False


def test_recall_and_sections():
    output = {"structure": {"plan": [{"text": "투석 가능성"}], "follow_up": [{"text": "연명의료 상의"}]}}
    score = score_structure(output, GOLD, INPUT)
    assert score.conversation_recall == 1.0
    assert score.items[0].sections == ("structure.plan",)
    assert score.context_only_leaks == []


def test_chart_only_term_without_context_is_a_leak():
    output = {"medications": [{"name": "midazolam infusion"}], "problems": [{"text": "r/o CIN"}]}
    assert score_structure(output, GOLD, INPUT).context_only_leaks == ["ctx_drug", "ctx_cin"]
    assert score_structure(output, GOLD, INPUT, context_given=True).context_only_leaks == []


def test_gold_is_checked_against_input():
    bad_gold = {"items": [
        {"id": "typo", "tier": "conversation", "must_match": [["투셕"]]},
        {"id": "mis_tiered", "tier": "context_only", "must_match": [["연명"]]},
    ]}
    errors = score_structure({}, bad_gold, INPUT).gold_errors
    assert errors == ["typo: conversation item not found in input",
                      "mis_tiered: context_only item is present in input"]


@pytest.fixture()
def answer_parser(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import answer_to_transcript

    return answer_to_transcript.parse_answer


ANSWER = """의사: 안녕하세요
환자 상태 설명 드리러 왔어요
보호자심장? 신장?
의사 심장이요
환자분 콩팥이 안좋아요

보호자:
알겠어요
"""


def test_answer_speaker_switches_and_warnings(answer_parser):
    segments, warnings = answer_parser(ANSWER, ("의사", "보호자"))
    assert [(s["speaker"], s["text"]) for s in segments] == [
        ("DOC", "안녕하세요"),
        ("DOC", "환자 상태 설명 드리러 왔어요"),  # "환자" not allowed to switch here
        ("GUARD", "심장? 신장?"),
        ("DOC", "심장이요"),
        ("DOC", "환자분 콩팥이 안좋아요"),
        ("GUARD", "알겠어요"),
    ]
    assert [w.split(":")[0] for w in warnings] == ["line 3", "line 4"]


def test_answer_with_patient_allowed_flags_the_ambiguous_line(answer_parser):
    segments, warnings = answer_parser(ANSWER)
    assert segments[1]["speaker"] == "PT"  # same shape as "의사 심장이요" -- hence the warning
    assert any(w.startswith("line 2:") for w in warnings)

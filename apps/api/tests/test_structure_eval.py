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


def test_term_candidate_quote_alone_is_not_a_conversation_hit():
    # spoken_text copies the transcript verbatim -- tasks/13-c
    quote = {"structure": {"term_candidates": [{"spoken_text": "투석을 해야 할 수도", "term": "dialysis"}]}}
    result = score_structure(quote, GOLD, INPUT).items[0]
    assert (result.hit, result.sections) == (False, ("structure.term_candidates",))
    kept = {"structure": {**quote["structure"], "plan": [{"text": "투석 가능성"}]}}
    assert score_structure(kept, GOLD, INPUT).items[0].hit is True


def test_term_candidates_still_count_for_leaks_and_frame_terms():
    gold = {"items": [{"id": "evt", "tier": "frame_term", "frame": "stroke", "must_match": [["evt"]]},
                      {"id": "ctx_drug", "tier": "context_only", "must_match": [["midazolam"]]}]}
    output = {"structure": {"term_candidates": [{"term": "EVT"}, {"term": "midazolam"}]}}
    score = score_structure(output, gold, INPUT, frames=frozenset({"stroke"}))
    assert (score.frame_recall, score.context_only_leaks) == (1.0, ["ctx_drug"])


def test_must_exclude_hit_is_always_a_leak():
    gold = {"items": [{"id": "profanity", "tier": "must_exclude", "must_match": [["욕설"]]}]}
    output = {"plan": [{"text": "욕설 포함 문장"}]}
    assert score_structure(output, gold, "의사: 욕설", context_given=True).excluded_leaks == ["profanity"]
    assert score_structure({"plan": []}, gold, "의사: 욕설").excluded_leaks == []


def test_frame_term_expected_with_frame_leak_without():
    gold = {"items": [{"id": "evt", "tier": "frame_term", "frame": "stroke", "must_match": [["evt"]]},
                      {"id": "asm", "tier": "frame_term", "frame": "seizure", "must_match": [["asm"]]}]}
    output = {"plan": [{"text": "EVT 보류 (용어 후보, 검수 필요)"}]}
    with_frame = score_structure(output, gold, INPUT, frames=frozenset({"stroke"}))
    assert (with_frame.frame_recall, with_frame.frame_leaks) == (1.0, [])
    without = score_structure(output, gold, INPUT)
    assert (without.frame_recall, without.frame_leaks) == (None, ["evt"])


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


ER_STYLE = """의사 1: (00:00)
보여서. 입원이 필요해요
의사2 (00:40)
12번이요.
noise: (00:56)
관계없는 대화
발화자 1 (01:47)
환자분 불편한 거 없어요?
보호자네.
-- 여기서부터 두번째 녹음, 첫녹음 6분 1초
의사 1 (00:02)
제 손 한번 꽉 쥐어볼게요. (00:05)
"""


def test_answer_numbered_speakers_noise_timestamps_and_offset(answer_parser):
    segments, warnings = answer_parser(ER_STYLE, aliases={"발화자 1": "의사 1"})
    assert [(s["speaker"], s["expected_role"], s["approx_start"], s["text"]) for s in segments] == [
        ("DOC", "doctor", 0, "보여서. 입원이 필요해요"),
        ("DOC2", "doctor", 40, "12번이요."),
        ("BG1", "background", 56, "관계없는 대화"),
        ("DOC", "doctor", 107, "환자분 불편한 거 없어요?"),  # alias applied
        ("GUARD", "guardian", 107, "네."),
        ("DOC", "doctor", 366, "제 손 한번 꽉 쥐어볼게요."),  # 361 s offset + 00:05, timestamp stripped
    ]
    assert any("no colon after '보호자'" in w for w in warnings)


def test_answer_unnamed_speaker_without_alias_stays_unknown(answer_parser):
    segments, warnings = answer_parser("발화자 4 (02:56)\nCT 찍어야 돼요\n")
    assert segments[0]["speaker"] == "SPK4" and segments[0]["expected_role"] == "unknown"
    assert any("unnamed speaker" in w for w in warnings)


def test_answer_honorific_header_line_switches_speaker_but_not_mid_sentence(answer_parser):
    text = "의사: 기관삽관 할 수도 있어요\n보호자분 (01:08)\n기관 삽관은요...\n의사: 네\n보호자분 걱정 마세요\n"
    segments, _ = answer_parser(text)
    assert [(s["speaker"], s["text"]) for s in segments] == [
        ("DOC", "기관삽관 할 수도 있어요"),
        ("GUARD", "기관 삽관은요..."),
        ("DOC", "네"),
        ("DOC", "보호자분 걱정 마세요"),  # address form inside the doctor's turn
    ]

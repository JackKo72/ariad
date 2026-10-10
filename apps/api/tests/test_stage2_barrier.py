"""Step 5: red flag rules first, then barrier classification. Synthetic data only."""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import pytest

from app.domain.stage2 import BarrierClassification, BarrierCode
from app.providers.mock import MockLLMProvider
from app.stage2 import barrier as barrier_module
from app.stage2.barrier import build_barrier_report, classify_free_text, detect_red_flags
from app.stage2.catalog import load_catalog
from app.stage2.config import load_barrier_config, load_red_flag_rules

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES = load_red_flag_rules()
CONFIG = load_barrier_config()
RED_FLAG_FIXTURE = json.loads((REPO_ROOT / "tests/fixtures/barriers/red_flags.json").read_text(encoding="utf-8"))
RESPONSES = json.loads((REPO_ROOT / "tests/fixtures/barriers/responses.json").read_text(encoding="utf-8"))
WEEK = "2026-W42"


class _ScriptedLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate_json(self, prompt_id, payload, stage_timer=None):
        self.calls.append((prompt_id, payload))
        return self.outputs.pop(0)


def _report(llm, **kw):
    return build_barrier_report("A-001", WEEK, llm_provider=llm, rules=RULES, config=CONFIG, **kw)


# ---------------------------------------------------------------- red flag gate (100%)


@pytest.mark.parametrize("case", RED_FLAG_FIXTURE["red_flags"], ids=lambda c: c["id"])
def test_every_red_flag_sentence_is_caught(case):
    assert case["expected_category"] in detect_red_flags(case["text"], RULES)


def test_red_flag_set_is_10_and_covers_every_design_category():
    cases = RED_FLAG_FIXTURE["red_flags"]
    assert len(cases) == 10
    assert {c["expected_category"] for c in cases} == set(RULES.categories)


def test_config_has_the_five_design_red_flags():
    assert set(RULES.categories) == {"new_neuro_deficit", "chest_pain", "syncope", "hypoglycemia", "repeated_falls"}


def test_hypoglycemia_threshold_matches_catalog_h2_safety_rule():
    h2 = next(a for a in load_catalog().actions if a.catalog_code == "H2")
    catalog_lt = next(r for r in h2.safety_rules if r.id == "hypoglycemia_immediate_safety_guidance").glucose_mg_dl_lt
    assert RULES.categories["hypoglycemia"].numeric.lt == catalog_lt


@pytest.mark.parametrize(
    "text, expected",
    [
        ("혈당 69 나왔어요", ["hypoglycemia"]),
        ("혈당 70 나왔어요", []),  # boundary: < 70 only
        ("혈당이 165 나왔어요", []),
        ("혈당 재는 걸 10일 동안 못 했어요", []),  # a duration, not a glucose value
        ("편마비 때문에 오래 걷기 힘들어요.", []),  # chronic deficit -> C-PHY, not a new one
        ("넘어질까 봐 무서워서 밖에 안 나갔어요.", []),  # fear of falling, no fall
    ],
)
def test_red_flag_boundaries_and_near_misses(text, expected):
    assert detect_red_flags(text, RULES) == expected


def test_negated_chest_pain_still_flags_on_purpose():
    """Rules err toward over-detection; a clinician clears false alarms."""
    assert detect_red_flags("가슴은 안 아파요", RULES) == ["chest_pain"]


def test_measured_value_alone_can_trigger():
    assert detect_red_flags(None, RULES, {"hypoglycemia": 58}) == ["hypoglycemia"]
    assert detect_red_flags(None, RULES, {"hypoglycemia": 70}) == []


def test_red_flag_skips_classification_and_alerts():
    llm = _ScriptedLLM([])
    report = _report(llm, free_text="걷다가 가슴이 조이는 것처럼 아팠어요.")
    assert llm.calls == []  # never reaches the LLM
    assert (report.red_flag, report.code, report.notify_clinician, report.needs_review) == (True, None, True, True)
    assert report.red_flag_categories == ["chest_pain"]
    assert report.guidance_text == RULES.guidance_template and "119" in report.guidance_text


def test_red_flag_overrides_a_selected_option():
    report = _report(_ScriptedLLM([]), selected_code=BarrierCode.MED, free_text="어제 쓰러졌어요")
    assert report.red_flag and report.code is None


# ---------------------------------------------------------------- classification


def test_selected_option_is_used_without_llm():
    llm = _ScriptedLLM([])
    report = _report(llm, selected_code=BarrierCode.O_PHY, free_text="비가 와서요")
    assert (report.code, report.classifier_confidence, report.follow_up_question, llm.calls) == (BarrierCode.O_PHY, None, None, [])


@pytest.mark.parametrize(
    "confidence, asks_follow_up",
    [(0.95, False), (0.7, False), (0.6999, True), (0.0, True)],
)
def test_confidence_threshold_controls_follow_up(confidence, asks_follow_up):
    report = _report(_ScriptedLLM([{"code": "O-SOC", "confidence": confidence, "rationale": ""}]), free_text="가족 때문에요")
    assert report.code == BarrierCode.O_SOC
    assert (report.follow_up_question is not None) == asks_follow_up == report.needs_review
    if asks_follow_up:
        assert "사회적 환경" in report.follow_up_question


def test_llm_payload_lists_all_ten_codes():
    llm = _ScriptedLLM([{"code": "MEAS", "confidence": 0.9, "rationale": ""}])
    _report(llm, free_text="앱이 안 열려요")
    prompt_id, payload = llm.calls[0]
    assert prompt_id == "classify_barrier"
    assert {c["code"] for c in payload["codes"]} == {c.value for c in BarrierCode}


def test_no_basis_is_stored_unclassified_for_review():
    report = _report(_ScriptedLLM([{"code": None, "confidence": 0.1, "rationale": ""}]), free_text="그냥요")
    assert (report.code, report.needs_review, report.follow_up_question) == (None, True, CONFIG.unclassified_follow_up)


def test_invalid_output_retried_once_then_unclassified():
    llm = _ScriptedLLM([{"code": "X-1", "confidence": 0.9, "rationale": ""}, {"code": "MED", "confidence": 3, "rationale": ""}])
    assert classify_free_text("감기요", llm, CONFIG) == (None, None)
    assert len(llm.calls) == 2


def test_invalid_then_valid_output_is_accepted():
    llm = _ScriptedLLM([{"oops": 1}, {"code": "MED", "confidence": 0.8, "rationale": ""}])
    assert classify_free_text("감기요", llm, CONFIG) == (BarrierCode.MED, 0.8)


@pytest.mark.parametrize("text", [None, "", "   "])
def test_nothing_to_classify_raises(text):
    with pytest.raises(ValueError):
        _report(_ScriptedLLM([]), free_text=text)


def test_barrier_config_describes_all_codes_with_design_responses():
    assert set(CONFIG.codes) == set(BarrierCode)
    assert CONFIG.min_confidence == 0.7
    assert CONFIG.codes[BarrierCode.PLAN].default_response == "ARIAD 1단계 품질 피드백으로도 기록"


def test_barrier_module_never_logs():
    source = inspect.getsource(barrier_module)
    assert "logging" not in source and "print(" not in source


def _empty_objects(node):
    if isinstance(node, dict):
        own = [node] if node.get("type") == "object" and not node.get("properties") else []
        return own + [x for v in node.values() for x in _empty_objects(v)]
    if isinstance(node, list):
        return [x for v in node for x in _empty_objects(v)]
    return []


def test_barrier_classification_is_openai_strict_compatible():
    from openai.lib._parsing._completions import type_to_response_format_param

    assert _empty_objects(type_to_response_format_param(BarrierClassification)["json_schema"]["schema"]) == []


# ---------------------------------------------------------------- eval set


def test_response_fixture_has_five_per_code():
    counts = {}
    for r in RESPONSES["responses"]:
        counts[r["expected_code"]] = counts.get(r["expected_code"], 0) + 1
    assert counts == {c.value: 5 for c in BarrierCode}


def test_eval_script_runs_on_mock():
    spec = importlib.util.spec_from_file_location("eval_barriers", REPO_ROOT / "scripts" / "eval_barriers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    red = module.evaluate_red_flags()
    assert (red["caught"], red["missed"]) == (10, [])
    cls = module.evaluate_classification(MockLLMProvider())
    assert cls["total"] == 50
    assert sum(sum(row.values()) for row in cls["matrix"].values()) == 50

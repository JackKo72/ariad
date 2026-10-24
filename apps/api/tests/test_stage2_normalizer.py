"""Step 3 normalizer: ActionDirective -> draft ActionItem. Synthetic data only."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.domain.models import ActionDirective
from app.domain.stage2 import ActionStatus, DirectiveClassification
from app.providers.mock import MockLLMProvider
from app.stage2.catalog import load_catalog
from app.stage2.normalizer import (
    catalog_default_target,
    classify_with_llm,
    match_by_domain,
    normalize_directives,
    parse_target_hint,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG = load_catalog()
ACTIONS = {a.catalog_code: a for a in CATALOG.actions}


class _ScriptedLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate_json(self, prompt_id, payload, stage_timer=None):
        self.calls.append((prompt_id, payload))
        return self.outputs.pop(0)


def _directive(**overrides) -> ActionDirective:
    data = dict(directive_id="AD-1", raw_text="국물은 드시지 마세요.", domain_hint="diet_sodium", needs_review=False)
    data.update(overrides)
    return ActionDirective(**data)


# ---------------------------------------------------------------- matching


def test_every_catalog_domain_matches_its_own_code():
    for action in CATALOG.actions:
        assert match_by_domain(action.domain, CATALOG) == action.catalog_code


@pytest.mark.parametrize("hint", [None, "", "sleep", "DIET_SODIUM"])
def test_unknown_domain_hint_does_not_match(hint):
    assert match_by_domain(hint, CATALOG) is None


def test_llm_fallback_used_only_without_domain_match():
    llm = _ScriptedLLM([{"catalog_code": "P1", "confidence": 0.9, "rationale": "걷기"}])
    items = normalize_directives([_directive(domain_hint=None, raw_text="매일 산책 나가세요.")], CATALOG, "P-x-v1", llm)
    assert items[0].catalog_code == "P1"
    assert items[0].needs_review is True  # LLM-matched always reviewed
    assert llm.calls[0][0] == "classify_action_directive"
    assert {c["catalog_code"] for c in llm.calls[0][1]["candidates"]} == set(ACTIONS)


def test_domain_hint_match_never_calls_llm():
    llm = _ScriptedLLM([])
    normalize_directives([_directive()], CATALOG, "P-x-v1", llm)
    assert llm.calls == []


def test_llm_invalid_code_retried_once_then_custom():
    llm = _ScriptedLLM([
        {"catalog_code": "Z9", "confidence": 0.9, "rationale": ""},
        {"catalog_code": "D2", "confidence": 1.5, "rationale": ""},
    ])
    assert classify_with_llm("물 많이 드세요.", CATALOG, llm) == "custom"
    assert len(llm.calls) == 2


def test_llm_malformed_then_valid_output_is_accepted():
    llm = _ScriptedLLM([{"oops": 1}, {"catalog_code": "D5", "confidence": 0.8, "rationale": ""}])
    assert classify_with_llm("콜라 줄이세요.", CATALOG, llm) == "D5"


def test_mock_classifier_never_guesses():
    assert classify_with_llm("잠을 7시간 주무세요.", CATALOG, MockLLMProvider()) == "custom"


def test_custom_item_is_draft_with_no_target_and_review():
    llm = _ScriptedLLM([{"catalog_code": "custom", "confidence": 0.2, "rationale": ""}])
    item = normalize_directives([_directive(domain_hint=None)], CATALOG, "P-x-v1", llm)[0]
    assert (item.catalog_code, item.target, item.needs_review, item.status) == ("custom", None, True, ActionStatus.DRAFT)


# ---------------------------------------------------------------- targets


@pytest.mark.parametrize(
    "code, hint, value",
    [
        ("P1", "주 5일 30분", 150),
        ("D2", "주 6일", 6),
        ("P2", "주 2회", 2),
        ("D4", "주 1회", 1),
        ("A1", "주 2잔", 2),
        ("P3", "하루 3번", 3),
    ],
)
def test_target_parsed_from_spoken_hint(code, hint, value):
    target = parse_target_hint(hint, ACTIONS[code])
    assert target.value == value
    assert target.unit == ACTIONS[code].default_target.unit
    assert target.comparator == ACTIONS[code].default_target.comparator


@pytest.mark.parametrize("code, hint", [("P1", "다섯 번 30분씩"), ("P1", None), ("H1", "주 7일"), ("D3", "주 3일")])
def test_target_not_parsed_when_unparseable_nested_or_todo(code, hint):
    assert parse_target_hint(hint, ACTIONS[code]) is None


def test_catalog_default_used_only_when_numeric():
    assert catalog_default_target(ACTIONS["D5"]).value == 0
    assert catalog_default_target(ACTIONS["D2"]) is None  # TODO_CLINICIAN
    assert catalog_default_target(ACTIONS["H1"]) is None  # nested pre_visit/routine


def test_spoken_target_wins_over_catalog_default():
    item = normalize_directives([_directive(domain_hint="activity_resistance", target_hint="주 3회")], CATALOG, "P-x-v1", _ScriptedLLM([]))[0]
    assert item.target.value == 3


def test_item_without_target_needs_review():
    item = normalize_directives([_directive()], CATALOG, "P-x-v1", _ScriptedLLM([]))[0]
    assert item.target is None and item.needs_review is True


def test_reviewed_directive_flag_carries_over():
    item = normalize_directives([_directive(domain_hint="diet_carb_sugar", needs_review=True)], CATALOG, "P-x-v1", _ScriptedLLM([]))[0]
    assert item.target is not None and item.needs_review is True


def test_clean_match_with_target_does_not_need_review():
    item = normalize_directives([_directive(domain_hint="diet_carb_sugar")], CATALOG, "P-x-v1", _ScriptedLLM([]))[0]
    assert (item.catalog_code, item.needs_review) == ("D5", False)


def test_items_are_sequential_drafts_linked_to_directives():
    directives = [_directive(directive_id="AD-1"), _directive(directive_id="AD-2", domain_hint="smoking")]
    items = normalize_directives(directives, CATALOG, "P-enc1-v1", _ScriptedLLM([]))
    assert [(i.action_id, i.plan_id, i.source_directive_id, i.status) for i in items] == [
        ("A-001", "P-enc1-v1", "AD-1", ActionStatus.DRAFT),
        ("A-002", "P-enc1-v1", "AD-2", ActionStatus.DRAFT),
    ]


# ---------------------------------------------------------------- LLM-facing schema


def _empty_objects(node):
    if isinstance(node, dict):
        own = [node] if node.get("type") == "object" and not node.get("properties") else []
        return own + [x for v in node.values() for x in _empty_objects(v)]
    if isinstance(node, list):
        return [x for v in node for x in _empty_objects(v)]
    return []


@pytest.mark.parametrize("model", ["DirectiveClassification", "ClinicalStructure"])
def test_llm_facing_models_are_openai_strict_compatible(model):
    from openai.lib._parsing._completions import type_to_response_format_param

    from app.domain.models import ClinicalStructure

    cls: type[BaseModel] = {"DirectiveClassification": DirectiveClassification, "ClinicalStructure": ClinicalStructure}[model]
    assert _empty_objects(type_to_response_format_param(cls)["json_schema"]["schema"]) == []


# ---------------------------------------------------------------- eval set


def _eval_module():
    spec = importlib.util.spec_from_file_location("eval_action_directives", REPO_ROOT / "scripts" / "eval_action_directives.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_visit_fixtures_are_well_formed():
    files = sorted((REPO_ROOT / "tests/fixtures/visits").glob("*.json"))
    assert len(files) == 20
    valid_codes = set(ACTIONS) | {"custom"}
    for f in files:
        visit = json.loads(f.read_text(encoding="utf-8"))
        assert visit["synthetic"] is True
        seg_roles = {s["id"]: s["role"] for s in visit["segments"]}
        assert len(seg_roles) == len(visit["segments"]), f.name
        assert set(seg_roles.values()) <= {"doctor", "patient", "guardian"}, f.name
        for exp in visit["expected_directives"]:
            assert exp["segment_ids"] and all(seg_roles[s] == "doctor" for s in exp["segment_ids"]), f.name
            assert exp["catalog_code"] in valid_codes, f.name
            assert exp["agreement"] in {"agreed", "hesitant", "refused", "unclear", None}, f.name


def test_score_visit_matching_rules():
    m = _eval_module()
    preds = [
        {"segment_ids": {"seg_001"}, "catalog_code": "D2", "agreement": "agreed", "needs_review": True},
        {"segment_ids": {"seg_003"}, "catalog_code": "P1", "agreement": None, "needs_review": True},
        {"segment_ids": {"seg_009"}, "catalog_code": "S1", "agreement": None, "needs_review": False},
    ]
    gold = [
        {"segment_ids": ["seg_001"], "catalog_code": "D2", "agreement": "hesitant"},
        {"segment_ids": ["seg_002", "seg_003"], "catalog_code": "P2", "agreement": None},
    ]
    assert m.score_visit(preds, gold) == {
        "pred": 3, "gold": 2, "detect_tp": 2, "code_tp": 1, "agreement_correct": 0, "needs_review": 2,
    }


def test_eval_runs_end_to_end_on_mock():
    result = _eval_module().evaluate(MockLLMProvider())
    total = result["total"]
    assert len(result["per_visit"]) == 20 and total["gold"] == 34
    assert 0 <= total["code_tp"] <= total["detect_tp"] <= min(total["pred"], total["gold"])

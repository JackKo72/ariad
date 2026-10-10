"""Step 4 judge: weekly CheckIns -> AdherenceJudgment. Pure, rule-based.
Synthetic data only."""

from __future__ import annotations

import datetime as dt
import inspect

import pytest
from pydantic import ValidationError

from app.domain.stage2 import ActionItem, AdherenceLabel, CheckIn, JudgeConfig
from app.stage2 import judge as judge_module
from app.stage2.catalog import load_catalog
from app.stage2.config import load_judge_config
from app.stage2.judge import iso_week, judge_week, label_for

CATALOG = {a.catalog_code: a for a in load_catalog().actions}
CONFIG = load_judge_config()
WEEK = "2026-W42"
MONDAY = dt.date.fromisocalendar(2026, 42, 1)


def _item(code: str, value: float, unit: str, comparator: str = ">=") -> ActionItem:
    return ActionItem(
        action_id=f"A-{code}", plan_id="P-enc1-v1", catalog_code=code,
        target={"value": value, "unit": unit, "comparator": comparator},
        status="active", approved_by="clinician-1",
    )


def _checkins(code: str, values: list[float], start: dt.date = MONDAY, step_days: int = 1) -> list[CheckIn]:
    return [
        CheckIn(checkin_id=f"C-{code}-{i}", action_id=f"A-{code}", date=start + dt.timedelta(days=i * step_days), value=v, source="self_report")
        for i, v in enumerate(values)
    ]


def _judge(code, value, unit, values, comparator=">=", **kw):
    return judge_week(_item(code, value, unit, comparator), CATALOG[code], _checkins(code, values, **kw), WEEK, CONFIG)


# ---------------------------------------------------------------- config


def test_config_matches_design_part_3_2():
    assert (CONFIG.adherent_min_rate, CONFIG.partial_min_rate, CONFIG.min_response_rate) == (0.8, 0.5, 0.5)


def test_config_rejects_inverted_thresholds():
    with pytest.raises(ValidationError):
        JudgeConfig(rule_version="x", adherent_min_rate=0.5, partial_min_rate=0.8, min_response_rate=0.5)


# ---------------------------------------------------------------- boundaries


@pytest.mark.parametrize(
    "rate, label",
    [
        (1.2, AdherenceLabel.ADHERENT),
        (0.8, AdherenceLabel.ADHERENT),
        (0.7999, AdherenceLabel.PARTIAL),
        (0.5, AdherenceLabel.PARTIAL),
        (0.4999, AdherenceLabel.NON_ADHERENT),
        (0.0, AdherenceLabel.NON_ADHERENT),
    ],
)
def test_rate_boundaries(rate, label):
    assert label_for(rate, 1.0, CONFIG) == label


@pytest.mark.parametrize(
    "response_rate, label",
    [(0.5, AdherenceLabel.ADHERENT), (0.4999, AdherenceLabel.INDETERMINATE), (0.0, AdherenceLabel.INDETERMINATE)],
)
def test_response_rate_boundary(response_rate, label):
    assert label_for(1.0, response_rate, CONFIG) == label


def test_end_to_end_exactly_0_8_is_adherent():
    # D2 국물 남기기 target 5 days/week, done 4 of 7 answered days -> 0.8
    j = _judge("D2", 5, "days_per_week", [1, 1, 1, 1, 0, 0, 0])
    assert (j.rate, j.label) == (0.8, AdherenceLabel.ADHERENT)


def test_end_to_end_exactly_0_5_is_partial():
    # P2 target 2 sessions/week, expected 2 check-ins, 1 done -> rate 0.5, response 0.5
    j = _judge("P2", 2, "sessions_per_week", [3], step_days=1)
    assert (j.rate, j.response_rate, j.label) == (0.5, 0.5, AdherenceLabel.PARTIAL)


def test_end_to_end_just_below_0_5_is_non_adherent():
    # P1 target 150 min/week, 74 minutes over answered days
    j = _judge("P1", 150, "minutes_per_week", [20, 20, 20, 14, 0, 0, 0])
    assert (j.rate, j.label) == (0.4933, AdherenceLabel.NON_ADHERENT)


def test_zero_checkins_is_indeterminate_without_rate():
    j = _judge("D2", 5, "days_per_week", [])
    assert (j.rate, j.response_rate, j.label) == (None, 0.0, AdherenceLabel.INDETERMINATE)


def test_low_response_rate_hides_rate():
    # D2 expects 7 daily answers; 3 answered (all done) -> response 0.43 < 0.5
    j = _judge("D2", 5, "days_per_week", [1, 1, 1])
    assert (j.label, j.rate, j.response_rate) == (AdherenceLabel.INDETERMINATE, None, 0.4286)


# ---------------------------------------------------------------- metric types


def test_amount_sums_minutes():
    j = _judge("P1", 150, "minutes_per_week", [30, 30, 30, 30, 30, 0, 0])
    assert (j.rate, j.label) == (1.0, AdherenceLabel.ADHERENT)


def test_frequency_per_day_unit_scales_to_week():
    # P3 3 prompted breaks/day -> 21/week; 15 of 21 prompts answered "yes"
    values = [1] * 15 + [0] * 6
    checkins = [
        CheckIn(checkin_id=f"C{i}", action_id="A-P3", date=MONDAY + dt.timedelta(days=i // 3), value=v, source="self_report")
        for i, v in enumerate(values)
    ]
    j = judge_week(_item("P3", 3, "prompted_breaks_per_day"), CATALOG["P3"], checkins, WEEK, CONFIG)
    assert (j.rate, j.response_rate, j.label) == (0.7143, 1.0, AdherenceLabel.PARTIAL)


def test_binary_zero_target_counts_clean_days():
    # S1 0 cigarettes/day: 5 smoke-free of 7 answered days
    j = _judge("S1", 0, "cigarettes_per_day", [0, 0, 3, 0, 0, 1, 0], comparator="<=")
    assert (j.rate, j.label) == (0.7143, AdherenceLabel.PARTIAL)


def test_binary_weekly_alcohol_zero_target():
    assert _judge("A1", 0, "drinks_per_week", [0], comparator="<=").label == AdherenceLabel.ADHERENT
    assert _judge("A1", 0, "drinks_per_week", [2], comparator="<=").label == AdherenceLabel.NON_ADHERENT


def test_at_most_target_above_zero():
    # A1 agreed <= 2 drinks/week: 2 -> 1.0, 4 -> 0.5
    assert _judge("A1", 2, "drinks_per_week", [2], comparator="<=").rate == 1.0
    assert _judge("A1", 2, "drinks_per_week", [4], comparator="<=").rate == 0.5


def test_frequency_at_most_sums_counts():
    # D4 <= 1 fried/pork meal per week
    assert _judge("D4", 1, "times_per_week", [0], comparator="<=").label == AdherenceLabel.ADHERENT
    assert _judge("D4", 1, "times_per_week", [3], comparator="<=").rate == 0.3333


def test_measurement_counts_measurements_not_values():
    # W1 weigh in once a week; the value is the weight, not a count
    j = _judge("W1", 1, "measurements_per_week", [71.5])
    assert (j.rate, j.label) == (1.0, AdherenceLabel.ADHERENT)


def test_measurement_in_days_counts_distinct_days():
    # H1 pre-visit 722: 7 days; measured on 4 days, 4 readings each
    checkins = [
        CheckIn(checkin_id=f"C{d}-{r}", action_id="A-H1", date=MONDAY + dt.timedelta(days=d), value=128, source="device")
        for d in range(4) for r in range(4)
    ]
    j = judge_week(_item("H1", 7, "days"), CATALOG["H1"], checkins, WEEK, CONFIG)
    assert (j.rate, j.response_rate, j.label) == (0.5714, 1.0, AdherenceLabel.PARTIAL)


# ---------------------------------------------------------------- input hygiene


def test_other_weeks_and_actions_are_ignored_and_duplicates_count_once():
    week_checkins = _checkins("D2", [1, 1, 1, 1, 1, 1, 1])
    noise = [
        CheckIn(checkin_id="next-week", action_id="A-D2", date=MONDAY + dt.timedelta(days=7), value=0, source="self_report"),
        CheckIn(checkin_id="other", action_id="A-P1", date=MONDAY, value=0, source="self_report"),
    ]
    j = judge_week(_item("D2", 7, "days_per_week"), CATALOG["D2"], week_checkins + week_checkins[:2] + noise, WEEK, CONFIG)
    assert (j.rate, j.response_rate) == (1.0, 1.0)


def test_judgment_carries_plan_id_and_rule_version():
    j = _judge("D2", 5, "days_per_week", [1] * 7)
    assert (j.plan_id, j.rule_version, j.week) == ("P-enc1-v1", "r1", WEEK)


def test_same_input_same_output():
    assert _judge("P1", 150, "minutes_per_week", [10, 50, 30]) == _judge("P1", 150, "minutes_per_week", [10, 50, 30])


def test_iso_week_format():
    assert iso_week(MONDAY) == WEEK and iso_week(dt.date(2027, 1, 1)) == "2026-W53"


@pytest.mark.parametrize(
    "item, code, match",
    [
        (ActionItem(action_id="A-D2", plan_id="P", catalog_code="D2"), "D2", "without a target"),
        (_item("D3", 3, "days_per_week"), "D3", "TODO_CLINICIAN"),
        (_item("D2", 5, "days_per_week"), "P1", "!="),
    ],
)
def test_unjudgeable_items_raise(item, code, match):
    with pytest.raises(ValueError, match=match):
        judge_week(item, CATALOG[code], [], WEEK, CONFIG)


def test_judge_module_has_no_llm_dependency():
    source = inspect.getsource(judge_module)
    assert "provider" not in source.lower() and "generate_json" not in source


def test_missed_measurements_lower_the_rate_instead_of_hiding_it():
    """Regression (found by the Step 7 simulation): H2 measured on 3 of 7
    targeted days must read as non-adherent, not indeterminate."""
    j = _judge("H2", 7, "measurements_per_week", [120, 118, 125])
    assert (j.label, j.rate, j.response_rate) == (AdherenceLabel.NON_ADHERENT, 0.4286, 1.0)


def test_zero_measurements_stay_indeterminate():
    j = _judge("H2", 7, "measurements_per_week", [])
    assert (j.label, j.rate) == (AdherenceLabel.INDETERMINATE, None)

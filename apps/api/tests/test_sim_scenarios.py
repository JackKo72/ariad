"""Step 7: scenarios A–D through the whole stage 2 pipeline on the mock
provider. Asserts the end-to-end behavior the design calls out, not exact
random draws. Synthetic data only."""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

from app.domain.stage2 import ActionStatus, AdherenceLabel
from app.providers.mock import MockLLMProvider

REPO_ROOT = Path(__file__).resolve().parents[3]


def _sim():
    spec = importlib.util.spec_from_file_location("run_scenarios", REPO_ROOT / "sim" / "run_scenarios.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass resolves its module via sys.modules
    spec.loader.exec_module(module)
    return module


SIM = _sim()
RESULTS = {r.scenario_id: r for r in SIM.run_all(MockLLMProvider())}


def _row(scenario, code):
    return next(r for r in RESULTS[scenario].report.rows if r.catalog_code == code)


def test_all_four_scenarios_run():
    assert set(RESULTS) == {"A", "B", "C", "D"}


def test_runs_are_reproducible():
    again = {r.scenario_id: r.markdown for r in SIM.run_all(MockLLMProvider())}
    assert again == {k: r.markdown for k, r in RESULTS.items()}


@pytest.mark.parametrize("scenario, codes", [("A", ["S1", "D2", "P1"]), ("B", ["P3", "P1", "D5", "H2"]), ("C", ["D2", "H1", "H2"]), ("D", ["P1"])])
def test_transcript_directives_become_the_approved_plan(scenario, codes):
    plan = RESULTS[scenario].plan
    assert [i.catalog_code for i in plan.items] == codes  # plan order = directive order = priority
    assert all(i.status == ActionStatus.ACTIVE and i.approved_by and i.target for i in plan.items)
    for row in RESULTS[scenario].report.rows:
        assert row.source_text and row.source_segment_ids  # every row traces back to the visit


def test_daily_question_limit_is_respected():
    limits = {"A": 2, "B": 3, "C": 3, "D": 3}
    for scenario, result in RESULTS.items():
        assert result.questions_asked <= 28 * limits[scenario]
    # A has no alert/device channels, so every check-in is an answered question
    assert max(Counter(c.date for c in RESULTS["A"].checkins).values()) <= limits["A"]


def test_scenario_a_question_limit_starves_walking():
    """Part 2-3 A: S1 and D2 are daily and the day holds 2 questions, so P1
    (also daily, lowest priority) is never asked -> 판정 불가. A real design
    conflict the report surfaces instead of hiding."""
    p1 = _row("A", "P1")
    assert p1.overall_label == AdherenceLabel.INDETERMINATE
    assert not [c for c in RESULTS["A"].checkins if c.action_id == "A-003"]


def test_scenario_c_is_answered_by_the_caregiver_and_raises_a_red_flag():
    result = RESULTS["C"]
    assert {i.respondent.value for i in result.plan.items} == {"caregiver"}
    assert all(c.respondent.value == "caregiver" for c in result.checkins)
    red = [a for a in result.report.alerts if a.kind == "red_flag"]
    assert red and red[0].catalog_code == "H2" and red[0].labels == ["혈당 <70 mg/dL"] and red[0].notify_clinician
    assert result.report.alerts[0].kind == "red_flag"  # red flags come first


def test_scenario_c_emotion_reason_goes_to_the_top():
    alerts = RESULTS["C"].report.alerts
    assert any(a.kind == "barrier" and a.labels == ["정서"] for a in alerts)


def test_scenario_d_matches_the_design_example():
    """Part 2-3 D: ~30% walking adherence, knee pain (C-PHY) 3x and weather
    (O-PHY) 2x -> lower target / substitute / rehab referral options."""
    row = _row("D", "P1")
    assert row.target_text == "주 120분"
    assert row.overall_label == AdherenceLabel.NON_ADHERENT and 0.2 <= row.overall_rate <= 0.4
    assert [(b.code.value, b.count) for b in row.top_barriers] == [("C-PHY", 3), ("O-PHY", 2)]
    assert row.suggestions[0] == "목표 하향 또는 대체 행동 검토"
    assert any("재활 의뢰" in s for s in row.suggestions)


def test_every_judgment_uses_the_approved_plan_version():
    for result in RESULTS.values():
        assert {j.plan_id for j in result.judgments} == {result.plan.plan_id}
        assert len(result.judgments) == 4 * len(result.plan.items)

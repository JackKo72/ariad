"""Step 6 pre-visit clinician report. Synthetic data only."""

from __future__ import annotations

import datetime as dt
import inspect

import pytest

from app.domain.models import ActionDirective, SourceSpan
from app.domain.stage2 import (
    ActionItem,
    ActionPlan,
    AdherenceJudgment,
    AdherenceLabel,
    BarrierCode,
    BarrierReport,
)
from app.stage2 import report as report_module
from app.stage2.catalog import load_catalog
from app.stage2.config import load_barrier_config, load_judge_config, load_red_flag_rules, load_report_config
from app.stage2.report import build_report, format_target, render_markdown, report_window

CATALOG = load_catalog()
CFG = dict(
    judge_config=load_judge_config(),
    barrier_config=load_barrier_config(),
    red_flag_rules=load_red_flag_rules(),
    report_config=load_report_config(),
)
VISIT = dt.date(2026, 11, 16)  # Monday; as_of 2026-11-09 -> weeks W42..W45
WEEKS = ["2026-W42", "2026-W43", "2026-W44", "2026-W45"]
PLAN_ID = "P-enc1-v1"


def _item(code, n, value, unit, comparator=">=", directive="AD-1", respondent="patient"):
    return ActionItem(
        action_id=f"A-{n:03d}", plan_id=PLAN_ID, catalog_code=code, source_directive_id=directive,
        target={"value": value, "unit": unit, "comparator": comparator},
        status="active", approved_by="dr", respondent=respondent,
    )


def _plan(*items, status="approved"):
    return ActionPlan(
        plan_id=PLAN_ID, encounter_id="enc1", version=1, status=status, items=list(items),
        created_at="t", approved_by="dr" if status != "draft" else None, approved_at="t" if status != "draft" else None,
    )


DIRECTIVE = ActionDirective(
    directive_id="AD-1", raw_text="주 4일 30분 걸으세요.",
    source_spans=[SourceSpan(segment_id="seg_001", quote="주 4일 30분 걸으세요.", speaker="A", role="doctor")],
)


def _j(week, rate, label, action="A-001", plan=PLAN_ID, response=1.0):
    return AdherenceJudgment(action_id=action, plan_id=plan, week=week, rate=rate, response_rate=response, label=label, rule_version="r1")


def _b(week, code=None, action="A-001", text="...", **kw):
    return BarrierReport(action_id=action, week=week, code=code, free_text=text, **kw)


def _red_flag(week, action="A-001"):
    return _b(week, action=action, text="어제 쓰러졌어요", red_flag=True, red_flag_categories=["syncope"],
              guidance_text="119", notify_clinician=True, needs_review=True)


def _build(plan, judgments=(), barriers=(), directives=(DIRECTIVE,)):
    return build_report(plan, list(directives), CATALOG, list(judgments), list(barriers), VISIT, **CFG)


# ---------------------------------------------------------------- window / formatting


def test_window_is_four_complete_weeks_before_as_of():
    as_of, weeks = report_window(VISIT, CFG["report_config"])
    assert (as_of, weeks) == (dt.date(2026, 11, 9), WEEKS)


def test_window_when_as_of_is_midweek_excludes_the_current_week():
    _, weeks = report_window(dt.date(2026, 11, 19), CFG["report_config"])  # as_of Thursday 11-12 (W46)
    assert weeks == WEEKS


@pytest.mark.parametrize(
    "value, unit, text",
    [(120, "minutes_per_week", "주 120분"), (0, "cigarettes_per_day", "하루 0개비"), (2.5, "drinks_per_week", "주 2.5잔 이하"), (3, "odd_unit", "3 odd_unit")],
)
def test_target_formatting(value, unit, text):
    assert format_target(value, unit, CFG["report_config"]) == text


# ---------------------------------------------------------------- rows


def test_row_traces_directive_to_rate_barriers_and_suggestions():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week"))
    judgments = [_j(w, r, AdherenceLabel.NON_ADHERENT) for w, r in zip(WEEKS, [0.3, 0.2, 0.4, 0.3])]
    barriers = [
        _b(WEEKS[0], "C-PHY"), _b(WEEKS[1], "C-PHY"), _b(WEEKS[1], "O-PHY"), _b(WEEKS[2], "O-PHY"), _b(WEEKS[3], "C-PHY"),
    ]
    [row] = _build(plan, judgments, barriers).rows
    assert (row.source_text, row.source_segment_ids, row.target_text) == ("주 4일 30분 걸으세요.", ["seg_001"], "주 120분")
    assert [w.rate for w in row.weekly] == [0.3, 0.2, 0.4, 0.3]
    assert (row.overall_rate, row.overall_label) == (0.3, AdherenceLabel.NON_ADHERENT)
    assert [(b.code, b.count, b.consecutive_weeks) for b in row.top_barriers] == [
        (BarrierCode.C_PHY, 3, 2), (BarrierCode.O_PHY, 2, 2),
    ]
    assert row.suggestions == [
        "목표 하향 또는 대체 행동 검토",
        "신체 능력 2주 연속 → 대체 행동 제안, 재활 의뢰 플래그",
        "물리적 환경·자원 2주 연속 → 실내 대안, 기기 대여 안내",
    ]


def test_non_consecutive_reason_gets_plain_suggestion():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week"))
    barriers = [_b(WEEKS[0], "MED"), _b(WEEKS[2], "MED")]
    [row] = _build(plan, [_j(WEEKS[0], 0.6, AdherenceLabel.PARTIAL)], barriers).rows
    assert "의학적 사건 → 계획 일시정지, 필요 시 의료진 알림" in row.suggestions


def test_top2_ties_follow_config_code_order():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week"))
    barriers = [_b(WEEKS[0], "MEAS"), _b(WEEKS[0], "O-PHY"), _b(WEEKS[1], "C-PSY")]
    [row] = _build(plan, [], barriers).rows
    assert [b.code.value for b in row.top_barriers] == ["C-PSY", "O-PHY"]


def test_unjudged_and_indeterminate_weeks_are_flagged_not_averaged():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week"))
    judgments = [
        _j(WEEKS[0], 0.9, AdherenceLabel.ADHERENT),
        _j(WEEKS[1], 0.9, AdherenceLabel.ADHERENT),
        _j(WEEKS[2], None, AdherenceLabel.INDETERMINATE, response=0.4),
    ]  # W45 has no judgment; mean response (1+1+0.4+0)/4 = 0.6 -> overall still judged
    [row] = _build(plan, judgments).rows
    assert row.weekly[3].label is None and row.overall_rate == 0.9
    assert row.overall_label == AdherenceLabel.ADHERENT
    assert "판정 불가·자료 없음 2주 (4주 수치에서 제외)" in row.suggestions


def test_low_mean_response_makes_overall_indeterminate():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week"))
    [row] = _build(plan, [_j(WEEKS[0], 0.9, AdherenceLabel.ADHERENT)]).rows  # mean response 0.25
    assert row.overall_label == AdherenceLabel.INDETERMINATE
    assert row.suggestions == ["응답 장벽(측정 문제)부터 확인"]


def test_judgments_of_other_plan_versions_and_weeks_are_ignored():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week"))
    judgments = [
        _j(WEEKS[0], 0.1, AdherenceLabel.NON_ADHERENT, plan="P-enc0-v1"),
        _j("2026-W41", 0.1, AdherenceLabel.NON_ADHERENT),
        _j(WEEKS[0], 0.9, AdherenceLabel.ADHERENT),
    ]
    [row] = _build(plan, judgments).rows
    assert [w.rate for w in row.weekly] == [0.9, None, None, None]


def test_item_without_directive_says_so():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week", directive=None))
    [row] = _build(plan, directives=[]).rows
    assert row.source_text is None and "(진료 대화 근거 없음)" in render_markdown(_build(plan, directives=[]))


def test_draft_plan_has_no_report():
    plan = _plan(ActionItem(action_id="A-001", plan_id=PLAN_ID, catalog_code="P1"), status="draft")
    with pytest.raises(ValueError, match="approved plan"):
        _build(plan)


# ---------------------------------------------------------------- alerts


def test_alerts_put_red_flags_first_then_top_codes_then_unclassified():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week"), _item("D2", 2, 6, "days_per_week", directive=None))
    barriers = [
        _b(WEEKS[0], None, needs_review=True),
        _b(WEEKS[0], "M-EMO", action="A-002", text="우울해요"),
        _b(WEEKS[1], "C-PHY"),  # not a top code -> no alert
        _red_flag(WEEKS[2], action="A-002"),
        _b("2026-W41", "PLAN"),  # outside window
    ]
    alerts = _build(plan, [], barriers).alerts
    assert [(a.kind, a.week, a.catalog_code) for a in alerts] == [
        ("red_flag", WEEKS[2], "D2"), ("barrier", WEEKS[0], "D2"), ("unclassified", WEEKS[0], "P1"),
    ]
    assert alerts[0].labels == ["실신"] and alerts[0].notify_clinician
    assert alerts[1].labels == ["정서"] and alerts[1].free_text == "우울해요"


def test_red_flag_reports_do_not_count_as_barriers_in_rows():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week"))
    [row] = _build(plan, [], [_red_flag(WEEKS[0])]).rows
    assert row.top_barriers == []


# ---------------------------------------------------------------- rendering / purity


def test_markdown_has_alert_section_table_and_no_row_free_text():
    plan = _plan(_item("P1", 1, 120, "minutes_per_week"))
    report = _build(plan, [_j(w, 0.3, AdherenceLabel.NON_ADHERENT) for w in WEEKS], [_b(WEEKS[0], "C-PHY", text="무릎이 아파요")])
    md = render_markdown(report)
    assert "## 먼저 확인할 항목" in md and "- 없음" in md
    assert "| P1 유산소 운동 (걷기) |" in md and "30% 미이행" in md
    assert "무릎이 아파요" not in md  # non-alert free text stays out of the table


def test_report_module_has_no_llm_or_logging():
    source = inspect.getsource(report_module)
    assert "generate_json" not in source and "logging" not in source and "print(" not in source

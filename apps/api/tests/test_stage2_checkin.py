"""Step 4 check-in question selection. Synthetic data only."""

from __future__ import annotations

import datetime as dt

import pytest

from app.domain.stage2 import ActionItem, ActionPlan, CheckinConfig, Respondent
from app.stage2.catalog import load_catalog
from app.stage2.checkin import daily_questions, is_due
from app.stage2.config import load_checkin_config, load_question_bank

CATALOG = load_catalog()
BANK = load_question_bank()
CONFIG = load_checkin_config()
MON, TUE, SUN = (dt.date.fromisocalendar(2026, 42, d) for d in (1, 2, 7))


def _item(code: str, i: int, status: str = "active", respondent: str = "patient") -> ActionItem:
    approved = status != "draft"
    return ActionItem(
        action_id=f"A-{i:03d}", plan_id="P-enc1-v1", catalog_code=code,
        target={"value": 1, "unit": "x", "comparator": ">="} if approved else None,
        respondent=respondent, status=status, approved_by="clinician-1" if approved else None,
        needs_review=code == "custom" and not approved,
    )


def _plan(*codes: str, status: str = "approved", item_status: str = "active", respondent: str = "patient") -> ActionPlan:
    return ActionPlan(
        plan_id="P-enc1-v1", encounter_id="enc1", version=1, status=status,
        items=[_item(c, i + 1, item_status, respondent) for i, c in enumerate(codes)],
        created_at="2026-10-09T10:00:00Z",
        approved_by=None if status == "draft" else "clinician-1",
        approved_at=None if status == "draft" else "2026-10-09T11:00:00Z",
    )


def _ask(plan, day, **kw):
    return daily_questions(plan, CATALOG, BANK, day, CONFIG, **kw)


def _ids(questions):
    return [(q.action_id, q.question_id, q.part_index) for q in questions]


# ---------------------------------------------------------------- safety gates


def test_draft_plan_sends_nothing():
    assert _ask(_plan("S1", "D2", status="draft", item_status="draft"), MON) == []


@pytest.mark.parametrize("item_status", ["approved", "paused", "retired"])
def test_only_active_items_are_asked(item_status):
    assert _ask(_plan("S1", item_status=item_status), MON) == []


def test_todo_templates_are_never_sent():
    # D1 weekly questionnaire is due on Sunday but its wording is TODO_CLINICIAN
    assert _ask(_plan("D1"), SUN) == []


# ---------------------------------------------------------------- limit and priority


def test_daily_limit_keeps_plan_order():
    # S1, D2, P1 daily + M1 (Mon/Wed/Fri) -> M1 is the 4th and is dropped
    questions = _ask(_plan("S1", "D2", "P1", "M1"), MON)
    assert _ids(questions) == [("A-001", "Q-S1-01", 0), ("A-002", "Q-D2-01", 0), ("A-003", "Q-P1-01", 0)]
    assert len(questions) == CONFIG.max_questions_per_day


def test_priority_order_changes_selection():
    assert [q.question_id for q in _ask(_plan("M1", "S1", "D2", "P1"), MON)] == ["Q-M1-01", "Q-S1-01", "Q-D2-01"]


def test_multi_part_question_that_does_not_fit_is_skipped_and_later_items_fill():
    # Sunday: S1 (1) + Q-S1-02 (1) = 2 slots; D5 needs 2 parts -> skipped; W1 (1) fits
    questions = _ask(_plan("S1", "D5", "W1"), SUN)
    assert _ids(questions) == [("A-001", "Q-S1-01", 0), ("A-001", "Q-S1-02", 0), ("A-003", "Q-W1-01", 0)]


def test_limit_is_read_from_config():
    one = CheckinConfig(max_questions_per_day=1, weekly_schedule=CONFIG.weekly_schedule)
    assert len(daily_questions(_plan("S1", "D2"), CATALOG, BANK, MON, one)) == 1


# ---------------------------------------------------------------- schedule


def test_weekly_items_follow_schedule():
    assert [q.question_id for q in _ask(_plan("P2"), TUE)] == ["Q-P2-01"]
    assert _ask(_plan("P2"), MON) == []


def test_shared_question_parts_go_to_their_own_action():
    questions = _ask(_plan("D4", "D5"), SUN)
    assert _ids(questions) == [("A-001", "Q-D45-01", 0), ("A-002", "Q-D45-01", 1), ("A-002", "Q-D45-01", 2)]


def test_non_question_channels_are_not_asked():
    # P3 is a daytime alert channel; H1/H2 have no fixed cadence
    for day in (MON, TUE, SUN):
        assert _ask(_plan("P3", "H1", "H2"), day) == []


def test_device_covered_items_skip_self_report():
    assert _ask(_plan("P1"), MON, device_covered=frozenset({"A-001"})) == []
    assert len(_ask(_plan("P1"), MON)) == 1


def test_custom_items_have_no_catalog_question():
    assert _ask(_plan("custom", "S1"), MON)[0].action_id == "A-002"


def test_unconfigured_weekly_frequency_raises():
    with pytest.raises(ValueError, match="weekly_schedule"):
        is_due(type(CATALOG.actions[0].check_method.cadence)(times=4, per="week"), MON, CONFIG)


# ---------------------------------------------------------------- wording


def test_caregiver_gets_caregiver_wording_and_answer_type():
    [q] = _ask(_plan("D2", respondent="caregiver"), MON)
    assert (q.respondent, q.text, q.answer_type, q.options) == (Respondent.CAREGIVER, "오늘 국 간을 줄이셨나요?", "yes_no", None)


def test_patient_gets_design_wording_with_choices():
    [q] = _ask(_plan("D2"), MON)
    assert (q.text, q.answer_type, q.options) == ("오늘 국물은 얼마나 드셨나요?", "choice", ["안 먹음", "반", "다"])
    assert q.review_status == "draft_unreviewed"


def test_question_bank_covers_every_catalog_question_id():
    referenced = set()
    for a in CATALOG.actions:
        referenced.add(a.check_method.question_id)
        if a.check_method.secondary_question_id:
            referenced.add(a.check_method.secondary_question_id)
    assert referenced == set(BANK.questions)


def test_shared_part_codes_point_at_actions_using_that_question():
    users = {}
    for a in CATALOG.actions:
        users.setdefault(a.check_method.question_id, set()).add(a.catalog_code)
    for qid, template in BANK.questions.items():
        for part in template.parts:
            assert part.for_code is None or part.for_code in users.get(qid, set()), (qid, part.for_code)

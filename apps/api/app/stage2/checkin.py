"""Daily check-in question selection (docs/ARIAD_stage2_design.md Part 2, Step 4).

Pure function: plan + catalog + question templates + day -> the questions
to send that day. Rules:

- Nothing is sent for a draft plan or for items that are not active
  (승인 전에는 환자에게 아무것도 가지 않는다).
- Priority is ActionPlan.items order. Each question part costs one slot;
  at most config max_questions_per_day slots. A question that does not
  fit in the remaining slots is skipped whole and lower-priority items may
  still fill the rest.
- Wording comes only from catalog/questions.yaml (patient or caregiver
  variant per ActionItem.respondent). Templates still marked
  TODO_CLINICIAN are never sent.
- Not handled here: daytime alert prompts (P3 channel daytime_prompt) and
  measurement entry with no fixed cadence (H1/H2 "measurement_days",
  "as_prescribed") -- those are separate channels.
"""

from __future__ import annotations

import datetime as dt
from typing import Union

from app.domain.stage2 import (
    ActionItem,
    ActionPlan,
    ActionStatus,
    Cadence,
    Catalog,
    CatalogAction,
    CheckinConfig,
    CheckInQuestion,
    QuestionBank,
    Respondent,
)

NON_QUESTION_CHANNELS = frozenset({"daytime_prompt"})
DEVICE_CHANNELS = frozenset({"device_or_daily_question", "device_or_value_entry", "value_entry_or_device"})


def is_due(cadence: Union[Cadence, str], day: dt.date, config: CheckinConfig) -> bool:
    if isinstance(cadence, str):  # as_prescribed / measurement_days / TODO_CLINICIAN
        return False
    if cadence.per == "day":
        return True
    if cadence.times not in config.weekly_schedule:
        raise ValueError(f"config/checkin.yaml weekly_schedule has no entry for {cadence.times} times/week")
    return day.isoweekday() in config.weekly_schedule[cadence.times]


def effective_cadence(item: ActionItem, action: CatalogAction) -> Union[Cadence, str]:
    """The clinician's per-item override, else the catalog cadence."""
    return item.check_cadence or action.check_method.cadence


def _scheduled_question_ids(item: ActionItem, action: CatalogAction) -> list[tuple[str, Union[Cadence, str]]]:
    method = action.check_method
    slots: list[tuple[str, Union[Cadence, str]]] = [(method.question_id, effective_cadence(item, action))]
    if method.secondary_question_id and method.secondary_cadence:
        slots.append((method.secondary_question_id, method.secondary_cadence))
    return slots


def daily_questions(
    plan: ActionPlan,
    catalog: Catalog,
    bank: QuestionBank,
    day: dt.date,
    config: CheckinConfig,
    device_covered: frozenset[str] = frozenset(),
) -> list[CheckInQuestion]:
    """device_covered: action_ids whose data arrives from a linked device
    today, so their self-report question is not asked."""
    if plan.status == ActionStatus.DRAFT:
        return []
    actions = {a.catalog_code: a for a in catalog.actions}
    selected: list[CheckInQuestion] = []
    asked: set[tuple[str, int]] = set()
    for item in plan.items:
        action = actions.get(item.catalog_code)
        if item.status != ActionStatus.ACTIVE or action is None:
            continue
        channel = action.check_method.channel
        if channel in NON_QUESTION_CHANNELS:
            continue
        if channel in DEVICE_CHANNELS and item.action_id in device_covered:
            continue
        for question_id, cadence in _scheduled_question_ids(item, action):
            if not is_due(cadence, day, config):
                continue
            template = bank.questions.get(question_id)
            if template is None or template.is_todo:
                continue
            parts = [
                (i, p)
                for i, p in enumerate(template.parts)
                if (p.for_code is None or p.for_code == item.catalog_code) and (question_id, i) not in asked
            ]
            if not parts or len(selected) + len(parts) > config.max_questions_per_day:
                continue
            for i, part in parts:
                caregiver = item.respondent == Respondent.CAREGIVER
                answer_type = (part.caregiver_answer_type or part.answer_type) if caregiver else part.answer_type
                selected.append(
                    CheckInQuestion(
                        action_id=item.action_id,
                        question_id=question_id,
                        part_index=i,
                        respondent=item.respondent,
                        text=part.caregiver if caregiver else part.patient,
                        answer_type=answer_type,
                        unit=part.unit,
                        options=part.options if answer_type == "choice" else None,
                        review_status=template.review_status,
                    )
                )
                asked.add((question_id, i))
    return selected


def never_asked_items(
    plan: ActionPlan,
    catalog: Catalog,
    bank: QuestionBank,
    config: CheckinConfig,
    week_start: dt.date,
    device_covered: frozenset[str] = frozenset(),
) -> list[str]:
    """Active question-channel items that one full week of daily_questions
    never selects -- e.g. a third daily item under a 2-question limit
    (Step 7 scenario A). Run at approval time so the clinician can change
    a cadence or the limit instead of finding 4 weeks of 판정 불가 later.
    Items on alert/device/no-cadence channels are not expected here."""
    asked = {
        q.action_id
        for offset in range(7)
        for q in daily_questions(plan, catalog, bank, week_start + dt.timedelta(days=offset), config, device_covered)
    }
    actions = {a.catalog_code: a for a in catalog.actions}
    expected = []
    for item in plan.items:
        action = actions.get(item.catalog_code)
        if item.status != ActionStatus.ACTIVE or action is None or item.action_id in device_covered:
            continue
        if action.check_method.channel in NON_QUESTION_CHANNELS:
            continue
        template = bank.questions.get(action.check_method.question_id)
        if isinstance(effective_cadence(item, action), str) or template is None or template.is_todo:
            continue
        expected.append(item.action_id)
    return [a for a in expected if a not in asked]

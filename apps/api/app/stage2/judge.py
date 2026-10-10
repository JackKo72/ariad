"""Weekly adherence judgment (docs/ARIAD_stage2_design.md Part 3-2, Step 4).

Pure, deterministic, no LLM (CLAUDE.md stage 2 rule): the same check-ins
always give the same judgment, and a clinician can recompute it by hand.
Thresholds come from config/judge.yaml; targets from the ActionItem.

CheckIn.value meaning, by metric_type:
- frequency, ">=" target (주 N일, 주 N회): one CheckIn per occasion,
  value > 0 means done. actual = number of done occasions.
- frequency, "<=" target (주 N회 이하): value = count in that report.
  actual = sum of values.
- amount (주 N분, 점수): value = minutes/points. actual = sum of values.
- binary (금연·금주, target 0): value = count (cigarettes, drinks);
  handled like "<=" below.
- measurement (체중·혈압·혈당): value = the measured number; adherence is
  whether it was measured. actual = number of check-ins (distinct days
  when the target unit is in days).

rate:
- ">=" targets: actual / weekly_target.
- "<=" targets with weekly_target 0: share of responded occasions with
  value 0 (e.g. smoke-free days / answered days).
- "<=" targets above 0: 1.0 if actual <= target, else target / actual.

weekly_target = target.value × 7 for "*_per_day" units, else target.value.
response_rate = check-ins received / check-ins expected this week (capped
at 1). Below config min_response_rate the label is indeterminate (판정
불가) and no rate-based label is given.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Optional

from app.domain.stage2 import (
    TODO_CLINICIAN,
    ActionItem,
    AdherenceJudgment,
    AdherenceLabel,
    Cadence,
    CatalogAction,
    CheckIn,
    Comparator,
    JudgeConfig,
    MetricType,
)

_RATE_DIGITS = 4


def iso_week(day: dt.date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def weekly_target(value: float, unit: str) -> float:
    return value * 7 if unit.endswith("_per_day") else value


def expected_responses(action: CatalogAction, target_per_week: float) -> Optional[int]:
    """Check-ins expected per week from the catalog cadence. Measurement
    actions without a fixed cadence expect one per targeted measurement."""
    cadence = action.check_method.cadence
    if isinstance(cadence, Cadence):
        return cadence.times * (7 if cadence.per == "day" else 1)
    if action.metric_type == MetricType.MEASUREMENT and target_per_week > 0:
        return math.ceil(target_per_week)
    return None


def compute_rate(
    metric_type: MetricType, comparator: Comparator, target_per_week: float, unit: str, checkins: list[CheckIn]
) -> Optional[float]:
    if not checkins:
        return None
    if metric_type == MetricType.MEASUREMENT:
        actual = len({c.date for c in checkins}) if unit.startswith("days") else len(checkins)
    elif metric_type == MetricType.FREQUENCY and comparator == Comparator.AT_LEAST:
        actual = sum(1 for c in checkins if c.value > 0)
    else:
        actual = sum(c.value for c in checkins)

    if comparator == Comparator.AT_LEAST:
        if target_per_week <= 0:
            raise ValueError("an at-least target must be above 0")
        return actual / target_per_week
    if target_per_week == 0:
        return sum(1 for c in checkins if c.value == 0) / len(checkins)
    return 1.0 if actual <= target_per_week else target_per_week / actual


def label_for(rate: Optional[float], response_rate: float, config: JudgeConfig) -> AdherenceLabel:
    if rate is None or response_rate < config.min_response_rate:
        return AdherenceLabel.INDETERMINATE
    if rate >= config.adherent_min_rate:
        return AdherenceLabel.ADHERENT
    if rate >= config.partial_min_rate:
        return AdherenceLabel.PARTIAL
    return AdherenceLabel.NON_ADHERENT


def judge_week(
    item: ActionItem,
    action: CatalogAction,
    checkins: list[CheckIn],
    week: str,
    config: JudgeConfig,
) -> AdherenceJudgment:
    """Judge one ActionItem for one ISO week. Check-ins for other actions
    or other weeks are ignored; duplicate checkin_ids count once."""
    if item.target is None:
        raise ValueError(f"{item.action_id}: cannot judge an item without a target")
    if action.catalog_code != item.catalog_code:
        raise ValueError(f"{item.action_id}: catalog action {action.catalog_code} != item {item.catalog_code}")
    if action.metric_type == TODO_CLINICIAN:
        raise ValueError(f"{item.catalog_code}: metric_type is still TODO_CLINICIAN")

    unique = {c.checkin_id: c for c in checkins if c.action_id == item.action_id and iso_week(c.date) == week}
    week_checkins = sorted(unique.values(), key=lambda c: (c.date, c.checkin_id))
    target = weekly_target(item.target.value, item.target.unit)
    metric_type = MetricType(action.metric_type)

    expected = expected_responses(action, target)
    if expected:
        response_rate = min(1.0, len(week_checkins) / expected)
    else:
        response_rate = 1.0 if week_checkins else 0.0

    rate = compute_rate(metric_type, item.target.comparator, target, item.target.unit, week_checkins)
    if rate is not None:
        rate = round(rate, _RATE_DIGITS)
    label = label_for(rate, response_rate, config)
    return AdherenceJudgment(
        action_id=item.action_id,
        plan_id=item.plan_id,
        week=week,
        rate=None if label == AdherenceLabel.INDETERMINATE else rate,
        response_rate=round(response_rate, _RATE_DIGITS),
        label=label,
        rule_version=config.rule_version,
    )

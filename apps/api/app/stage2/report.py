"""Pre-visit clinician report (docs/ARIAD_stage2_design.md Part 3-1·3-4·5-1, Step 6).

Pure, deterministic, no LLM: given the approved plan, the stage-1
directives it came from, the weekly judgments and barrier reports, build
one row per ActionItem --

    원 발화(source_span) -> 목표 -> 4주 이행률 -> 주요 사유 Top2 -> 제안

-- and put red flags, the config top_codes (PLAN, M-REF, M-EMO, MED) and
unclassified reasons at the top. The window is the config `weeks` complete
ISO weeks (Mon–Sun) before `days_before_visit` days ahead of the visit.

The report is clinician-facing: it carries directive text and patient
free text for alerts. It is never returned by a patient endpoint and must
not be logged.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Optional

from app.domain.models import ActionDirective
from app.domain.stage2 import (
    ActionPlan,
    ActionStatus,
    AdherenceJudgment,
    AdherenceLabel,
    BarrierConfig,
    BarrierCount,
    BarrierReport,
    Catalog,
    ClinicianReport,
    JudgeConfig,
    RedFlagRules,
    ReportAlert,
    ReportConfig,
    ReportRow,
    WeeklyResult,
)
from app.stage2.judge import iso_week, label_for

_TOP_BARRIERS = 2  # Part 5-1 / Step 6: "주요 사유 Top2"


def report_window(visit_date: dt.date, config: ReportConfig) -> tuple[dt.date, list[str]]:
    """(as_of, weeks oldest-first). Weeks are the last complete Mon–Sun
    weeks ending before as_of."""
    as_of = visit_date - dt.timedelta(days=config.days_before_visit)
    last_sunday = as_of - dt.timedelta(days=as_of.isoweekday())
    weeks = [iso_week(last_sunday - dt.timedelta(weeks=k)) for k in reversed(range(config.weeks))]
    return as_of, weeks


def format_target(value: float, unit: str, config: ReportConfig) -> str:
    shown = int(value) if float(value).is_integer() else value
    template = config.unit_labels.get(unit)
    return template.format(v=shown) if template else f"{shown} {unit}"


def _longest_run(weeks_with_code: set[str], weeks: list[str]) -> int:
    best = run = 0
    for week in weeks:
        run = run + 1 if week in weeks_with_code else 0
        best = max(best, run)
    return best


def _top_barriers(reports: list[BarrierReport], weeks: list[str], barrier_config: BarrierConfig) -> list[BarrierCount]:
    coded = [r for r in reports if r.code is not None]
    counts = Counter(r.code for r in coded)
    order = list(barrier_config.codes)  # config order breaks ties deterministically
    ranked = sorted(counts, key=lambda c: (-counts[c], order.index(c)))[:_TOP_BARRIERS]
    return [
        BarrierCount(
            code=code,
            label_ko=barrier_config.codes[code].label_ko,
            count=counts[code],
            consecutive_weeks=_longest_run({r.week for r in coded if r.code == code}, weeks),
        )
        for code in ranked
    ]


def _suggestions(
    label: AdherenceLabel, top: list[BarrierCount], barrier_config: BarrierConfig, config: ReportConfig
) -> list[str]:
    out = [config.label_suggestions[label]]
    for b in top:
        response = barrier_config.codes[b.code].default_response
        if b.consecutive_weeks >= config.consecutive_weeks_for_suggestion:
            out.append(f"{b.label_ko} {b.consecutive_weeks}주 연속 → {response}")
        else:
            out.append(f"{b.label_ko} → {response}")
    return list(dict.fromkeys(out))


def _indeterminate_note(weekly: list[WeeklyResult], overall: AdherenceLabel) -> list[str]:
    """The 4-week rate averages judged weeks only; say how many were not
    judged so a good average cannot hide them."""
    missing = sum(1 for w in weekly if w.label in (None, AdherenceLabel.INDETERMINATE))
    if missing == 0 or overall == AdherenceLabel.INDETERMINATE:
        return []
    return [f"판정 불가·자료 없음 {missing}주 (4주 수치에서 제외)"]


def _alerts(
    plan: ActionPlan,
    barriers: list[BarrierReport],
    weeks: list[str],
    red_flag_rules: RedFlagRules,
    barrier_config: BarrierConfig,
    config: ReportConfig,
) -> list[ReportAlert]:
    codes = {i.action_id: i.catalog_code for i in plan.items}
    alerts = []
    for b in barriers:
        if b.action_id not in codes or b.week not in weeks:
            continue
        common = dict(action_id=b.action_id, catalog_code=codes[b.action_id], week=b.week, free_text=b.free_text)
        if b.red_flag:
            labels = [red_flag_rules.categories[c].label_ko if c in red_flag_rules.categories else c for c in b.red_flag_categories]
            alerts.append(ReportAlert(kind="red_flag", labels=labels, notify_clinician=True, **common))
        elif b.code is None:
            alerts.append(ReportAlert(kind="unclassified", labels=["분류 안 됨"], **common))
        elif b.code in config.top_codes:
            alerts.append(ReportAlert(kind="barrier", labels=[barrier_config.codes[b.code].label_ko], **common))
    kind_order = {"red_flag": 0, "barrier": 1, "unclassified": 2}
    return sorted(alerts, key=lambda a: (kind_order[a.kind], a.week, a.action_id))


def build_report(
    plan: ActionPlan,
    directives: list[ActionDirective],
    catalog: Catalog,
    judgments: list[AdherenceJudgment],
    barriers: list[BarrierReport],
    visit_date: dt.date,
    *,
    judge_config: JudgeConfig,
    barrier_config: BarrierConfig,
    red_flag_rules: RedFlagRules,
    report_config: ReportConfig,
) -> ClinicianReport:
    if plan.status == ActionStatus.DRAFT:
        raise ValueError("a report is built only for an approved plan")
    as_of, weeks = report_window(visit_date, report_config)
    by_directive = {d.directive_id: d for d in directives}
    names = {a.catalog_code: a.name_ko for a in catalog.actions}

    rows = []
    for item in plan.items:
        if item.status == ActionStatus.DRAFT or item.target is None:
            continue
        found = {
            j.week: j for j in judgments if j.action_id == item.action_id and j.plan_id == plan.plan_id and j.week in weeks
        }
        weekly = [
            WeeklyResult(week=w, label=found[w].label, rate=found[w].rate, response_rate=found[w].response_rate)
            if w in found
            else WeeklyResult(week=w)
            for w in weeks
        ]
        rates = [r.rate for r in weekly if r.rate is not None]
        overall_rate: Optional[float] = round(sum(rates) / len(rates), 4) if rates else None
        mean_response = sum(r.response_rate or 0.0 for r in weekly) / len(weekly)
        overall_label = label_for(overall_rate, mean_response, judge_config)
        item_barriers = [b for b in barriers if b.action_id == item.action_id and b.week in weeks and not b.red_flag]
        top = _top_barriers(item_barriers, weeks, barrier_config)
        directive: Optional[ActionDirective] = by_directive.get(item.source_directive_id or "")
        rows.append(
            ReportRow(
                action_id=item.action_id,
                catalog_code=item.catalog_code,
                name_ko=names.get(item.catalog_code, item.catalog_code),
                respondent=item.respondent,
                source_text=directive.raw_text if directive else None,
                source_segment_ids=[s.segment_id for s in directive.source_spans] if directive else [],
                target_text=format_target(item.target.value, item.target.unit, report_config),
                weekly=weekly,
                overall_rate=overall_rate,
                overall_label=overall_label,
                top_barriers=top,
                suggestions=_suggestions(overall_label, top, barrier_config, report_config)
                + _indeterminate_note(weekly, overall_label),
            )
        )

    return ClinicianReport(
        plan_id=plan.plan_id,
        encounter_id=plan.encounter_id,
        visit_date=visit_date,
        as_of=as_of,
        weeks=weeks,
        alerts=_alerts(plan, barriers, weeks, red_flag_rules, barrier_config, report_config),
        rows=rows,
        rule_version=judge_config.rule_version,
        report_config_version=report_config.config_version,
    )


_LABEL_KO = {
    AdherenceLabel.ADHERENT: "완전 이행",
    AdherenceLabel.PARTIAL: "부분 이행",
    AdherenceLabel.NON_ADHERENT: "미이행",
    AdherenceLabel.INDETERMINATE: "판정 불가",
}


def _pct(rate: Optional[float]) -> str:
    return "–" if rate is None else f"{round(rate * 100)}%"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: ClinicianReport) -> str:
    """Clinician-facing Markdown. Contains directive and patient text."""
    lines = [
        f"# 외래 전 생활습관 리포트 — 외래 {report.visit_date.isoformat()} (기준일 {report.as_of.isoformat()})",
        "",
        f"기간: {report.weeks[0]} ~ {report.weeks[-1]} · 판정 규칙 {report.rule_version} · 리포트 설정 {report.report_config_version}",
        "",
        "## 먼저 확인할 항목",
        "",
    ]
    if report.alerts:
        kind_ko = {"red_flag": "🚨 RED FLAG", "barrier": "사유", "unclassified": "분류 안 됨"}
        for a in report.alerts:
            alert = "의료진 알림 · " if a.notify_clinician else ""
            text = f' — "{_cell(a.free_text)}"' if a.free_text else ""
            lines.append(f"- **{kind_ko[a.kind]}** {a.week} · {a.catalog_code} ({a.action_id}) · {alert}{', '.join(a.labels)}{text}")
    else:
        lines.append("- 없음")
    lines += [
        "",
        "## 행동별 요약",
        "",
        "| 행동 | 원 발화 | 목표 | 주별 이행률 | 4주 | 주요 사유 Top2 | 제안 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.rows:
        source = f'"{_cell(r.source_text)}" ({", ".join(r.source_segment_ids)})' if r.source_text else "(진료 대화 근거 없음)"
        weekly = " / ".join(_pct(w.rate) if w.label != AdherenceLabel.INDETERMINATE else "?" for w in r.weekly)
        barriers = ", ".join(f"{b.label_ko}({b.code.value}) {b.count}회" for b in r.top_barriers) or "–"
        respondent = " · 보호자 응답" if r.respondent.value == "caregiver" else ""
        lines.append(
            f"| {r.catalog_code} {r.name_ko}{respondent} | {source} | {r.target_text} | {weekly} | "
            f"{_pct(r.overall_rate)} {_LABEL_KO[r.overall_label]} | {barriers} | {_cell('; '.join(r.suggestions))} |"
        )
    lines += ["", "주별 이행률의 `?`는 응답률이 기준 미만이라 판정하지 않은 주, `–`는 데이터가 없는 주다."]
    return "\n".join(lines) + "\n"


"""Run Part 2-3 scenarios A–D through the whole stage 2 pipeline (Step 7).

Per scenario (all synthetic):
  transcript -> structure_encounter (action_directives) -> normalize_directives
  -> simulated clinician approval (targets, respondent) -> 4 weeks of days:
     daily_questions -> simulated answers -> CheckIns
     (+ alert/measurement channels the question selector does not cover)
  -> judge_week per item per week -> barrier reports for partial/non-adherent
     weeks and red-flag checks on measurements -> build_report -> Markdown.

Virtual answers come from a seeded behavior model in sim/scenarios.yaml,
not an LLM, so every run is reproducible. Classification uses whatever
LLM provider app.dependencies resolves (mock by default).

    python3 sim/run_scenarios.py                 # all scenarios, print reports
    python3 sim/run_scenarios.py --only D --out sim/output
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.domain.models import ActionDirective  # noqa: E402
from app.domain.stage2 import (  # noqa: E402
    ActionItem,
    ActionPlan,
    ActionStatus,
    ActionTarget,
    AdherenceJudgment,
    AdherenceLabel,
    BarrierReport,
    Cadence,
    CatalogAction,
    CheckIn,
    CheckinConfig,
    ClinicianReport,
    Comparator,
    MetricType,
    Respondent,
)
from app.providers.base import LLMProvider  # noqa: E402
from app.stage2.barrier import build_barrier_report, detect_red_flags  # noqa: E402
from app.stage2.catalog import load_catalog  # noqa: E402
from app.stage2.checkin import NON_QUESTION_CHANNELS, daily_questions  # noqa: E402
from app.stage2.config import (  # noqa: E402
    load_barrier_config,
    load_checkin_config,
    load_judge_config,
    load_question_bank,
    load_red_flag_rules,
    load_report_config,
)
from app.stage2.judge import iso_week, judge_week  # noqa: E402
from app.stage2.normalizer import normalize_directives  # noqa: E402
from app.stage2.report import build_report, render_markdown  # noqa: E402

SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.yaml"
SIM_CLINICIAN = "sim-clinician"


@dataclass
class ScenarioResult:
    scenario_id: str
    plan: ActionPlan
    directives: list[ActionDirective]
    checkins: list[CheckIn] = field(default_factory=list)
    judgments: list[AdherenceJudgment] = field(default_factory=list)
    barriers: list[BarrierReport] = field(default_factory=list)
    questions_asked: int = 0
    report: Optional[ClinicianReport] = None
    markdown: str = ""


def load_scenarios(path: Path = SCENARIOS_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def approve_plan(
    scenario: dict[str, Any], encounter_id: str, draft_items: list[ActionItem], approved_at: str
) -> ActionPlan:
    """Simulated clinician review: fill/override targets, set respondent,
    drop unmatched (custom) items, then approve and activate."""
    clinician = scenario["clinician"]
    overrides = clinician.get("targets") or {}
    respondent = Respondent(clinician.get("respondent", "patient"))
    items = []
    for item in draft_items:
        if item.catalog_code == "custom":
            continue
        target = ActionTarget(**overrides[item.catalog_code]) if item.catalog_code in overrides else item.target
        if target is None:
            raise ValueError(f"scenario {scenario['id']}: {item.catalog_code} has no target; add one under clinician.targets")
        items.append(
            item.model_copy(
                update={
                    "target": target,
                    "respondent": respondent,
                    "status": ActionStatus.ACTIVE,
                    "approved_by": SIM_CLINICIAN,
                    "needs_review": False,
                }
            )
        )
    plan_id = draft_items[0].plan_id if draft_items else f"P-{encounter_id}-v1"
    return ActionPlan(
        plan_id=plan_id,
        encounter_id=encounter_id,
        version=1,
        status=ActionStatus.APPROVED,
        items=[ActionItem.model_validate(i.model_dump()) for i in items],
        created_at=approved_at,
        approved_by=SIM_CLINICIAN,
        approved_at=approved_at,
    )


def _value(behavior: dict[str, Any], comparator: Comparator, done: bool) -> float:
    if comparator == Comparator.AT_LEAST:
        return float(behavior.get("done_value", 1) if done else behavior.get("miss_value", 0))
    return float(behavior.get("done_value", 0) if done else behavior.get("miss_value", 1))


def _direct_occasions(action: CatalogAction, item: ActionItem, device_covered: frozenset[str]) -> int:
    """Occasions per day that bypass the question selector: alert prompts,
    linked devices, and measurement entry without a fixed cadence."""
    cadence = action.check_method.cadence
    if action.check_method.channel in NON_QUESTION_CHANNELS and isinstance(cadence, Cadence) and cadence.per == "day":
        return cadence.times
    if item.action_id in device_covered:
        return 1
    if action.metric_type == MetricType.MEASUREMENT and isinstance(cadence, str):
        return 1
    return 0


def run_scenario(scenario: dict[str, Any], settings: dict[str, Any], llm_provider: LLMProvider) -> ScenarioResult:
    from app.pipeline.structure import structure_encounter

    catalog = load_catalog()
    actions = {a.catalog_code: a for a in catalog.actions}
    base_checkin = load_checkin_config()
    checkin_config = CheckinConfig(
        max_questions_per_day=scenario.get("max_questions_per_day", base_checkin.max_questions_per_day),
        weekly_schedule=base_checkin.weekly_schedule,
    )
    bank = load_question_bank()
    judge_config = load_judge_config()
    rules, barrier_config, report_config = load_red_flag_rules(), load_barrier_config(), load_report_config()

    start: dt.date = settings["start_date"]
    n_weeks: int = settings["weeks"]
    rng = random.Random(f"{settings['seed']}-{scenario['id']}")
    encounter_id = f"sim-{scenario['id']}"

    structure = structure_encounter(scenario["transcript"].strip(), llm_provider)
    draft = normalize_directives(structure.action_directives, catalog, f"P-{encounter_id}-v1", llm_provider)
    plan = approve_plan(scenario, encounter_id, draft, f"{start.isoformat()}T09:00:00")
    result = ScenarioResult(scenario["id"], plan, structure.action_directives)

    device_covered = frozenset(scenario.get("device_covered", []))
    events = {(e["week"], e["day"], e["code"]): e for e in scenario.get("events", [])}
    red_flag_categories = settings.get("red_flag_measurements", {})
    counter = 0

    def add_checkin(item: ActionItem, day: dt.date, value: float, source: str) -> None:
        nonlocal counter
        counter += 1
        result.checkins.append(
            CheckIn(
                checkin_id=f"C-{scenario['id']}-{counter:04d}", action_id=item.action_id, date=day,
                value=value, source=source, respondent=item.respondent,
            )
        )

    for week_index in range(n_weeks):
        for day_index in range(7):
            day = start + dt.timedelta(weeks=week_index, days=day_index)
            asked = daily_questions(plan, catalog, bank, day, checkin_config, device_covered)
            result.questions_asked += len(asked)
            answered: set[str] = set()
            for question in asked:
                if question.action_id in answered:
                    continue  # one CheckIn per action per day (first part carries the judged value)
                item = next(i for i in plan.items if i.action_id == question.action_id)
                behavior = scenario["behavior"].get(item.catalog_code, {})
                if rng.random() >= behavior.get("respond", 1.0):
                    continue
                done = rng.random() < behavior.get("done", [1.0] * n_weeks)[week_index]
                add_checkin(item, day, _value(behavior, item.target.comparator, done), "self_report")
                answered.add(item.action_id)

            for item in plan.items:
                action = actions[item.catalog_code]
                behavior = scenario["behavior"].get(item.catalog_code, {})
                event = events.get((week_index, day_index, item.catalog_code))
                for _ in range(_direct_occasions(action, item, device_covered)):
                    if action.metric_type == MetricType.MEASUREMENT:
                        if event is None and rng.random() >= behavior.get("done", [1.0] * n_weeks)[week_index]:
                            continue  # not measured that day
                        value = float(event["measured_value"] if event else behavior.get("measured_value", 0))
                        add_checkin(item, day, value, "device")
                        category = red_flag_categories.get(item.catalog_code)
                        if category and detect_red_flags(None, rules, {category: value}):
                            result.barriers.append(
                                build_barrier_report(
                                    item.action_id, iso_week(day), llm_provider=llm_provider, rules=rules,
                                    config=barrier_config, measured_values={category: value},
                                )
                            )
                    elif rng.random() < behavior.get("respond", 1.0):
                        done = rng.random() < behavior.get("done", [1.0] * n_weeks)[week_index]
                        add_checkin(item, day, _value(behavior, item.target.comparator, done), "self_report")

        week = iso_week(start + dt.timedelta(weeks=week_index))
        for item in plan.items:
            judgment = judge_week(item, actions[item.catalog_code], result.checkins, week, judge_config)
            result.judgments.append(judgment)
            if judgment.label not in (AdherenceLabel.PARTIAL, AdherenceLabel.NON_ADHERENT):
                continue
            texts = (scenario.get("barriers", {}).get(item.catalog_code) or [[]] * n_weeks)[week_index]
            for text in texts:
                result.barriers.append(
                    build_barrier_report(
                        item.action_id, week, llm_provider=llm_provider, rules=rules, config=barrier_config, free_text=text
                    )
                )

    visit_date = start + dt.timedelta(weeks=n_weeks, days=report_config.days_before_visit)
    result.report = build_report(
        plan, result.directives, catalog, result.judgments, result.barriers, visit_date,
        judge_config=judge_config, barrier_config=barrier_config, red_flag_rules=rules, report_config=report_config,
    )
    result.markdown = f"<!-- 시나리오 {scenario['id']}: {scenario['description']} (가상 데이터) -->\n" + render_markdown(result.report)
    return result


def run_all(llm_provider: LLMProvider, only: Optional[set[str]] = None) -> list[ScenarioResult]:
    settings = load_scenarios()
    return [
        run_scenario(s, settings, llm_provider)
        for s in settings["scenarios"]
        if only is None or s["id"] in only
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="scenario ids, e.g. --only A D")
    parser.add_argument("--out", type=Path, help="write each report as <out>/scenario_<id>.md")
    args = parser.parse_args()

    from app.dependencies import get_llm_provider

    results = run_all(get_llm_provider(), set(args.only) if args.only else None)
    for r in results:
        print(r.markdown)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / f"scenario_{r.scenario_id}.md").write_text(r.markdown, encoding="utf-8")


if __name__ == "__main__":
    main()

"""Normalizer: ActionDirective -> draft ActionItem (docs/ARIAD_stage2_design.md Part 5-1 step 3).

Matching order: domain_hint (deterministic) -> LLM classification -> "custom".
Every item comes out status=draft; nothing reaches a patient until a
clinician approves the plan. Targets are parsed only from what the doctor
said (target_hint) or taken from a numeric catalog default -- never
invented. Clinical numbers come from catalog/actions.yaml; the regexes
here only read Korean count words ("주 5일", "하루 2번").
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import ValidationError

from app.domain.stage2 import (
    CUSTOM_CATALOG_CODE,
    TODO_CLINICIAN,
    ActionDirective,
    ActionItem,
    ActionStatus,
    ActionTarget,
    Catalog,
    CatalogAction,
    CatalogTarget,
    DirectiveClassification,
)
from app.providers.base import LLMProvider

# unit -> regex whose group 1 is the count (group 2, if present, minutes).
_TARGET_PATTERNS: dict[str, re.Pattern[str]] = {
    "minutes_per_week": re.compile(r"주\s*(\d+)\s*(?:일|회|번)\s*(\d+)\s*분"),
    "days_per_week": re.compile(r"주\s*(\d+)\s*(?:일|회|번)"),
    "sessions_per_week": re.compile(r"주\s*(\d+)\s*(?:회|번|일)"),
    "times_per_week": re.compile(r"주\s*(\d+)\s*(?:회|번)"),
    "measurements_per_week": re.compile(r"주\s*(\d+)\s*(?:회|번|일)"),
    "drinks_per_week": re.compile(r"주\s*(\d+)\s*잔"),
    "sugary_drinks_per_week": re.compile(r"주\s*(\d+)\s*(?:잔|병|캔|회|번)"),
    "cigarettes_per_day": re.compile(r"하루\s*(\d+)\s*개비"),
    "prompted_breaks_per_day": re.compile(r"하루\s*(\d+)\s*(?:번|회)"),
}


def match_by_domain(domain_hint: Optional[str], catalog: Catalog) -> Optional[str]:
    if not domain_hint:
        return None
    matches = [a.catalog_code for a in catalog.actions if a.domain == domain_hint]
    return matches[0] if len(matches) == 1 else None


def _valid_classification(raw: dict, valid_codes: set[str]) -> Optional[DirectiveClassification]:
    try:
        result = DirectiveClassification.model_validate(raw)
    except ValidationError:
        return None
    if result.catalog_code not in valid_codes or not 0.0 <= result.confidence <= 1.0:
        return None
    return result


def classify_with_llm(raw_text: str, catalog: Catalog, llm_provider: LLMProvider) -> str:
    """LLM fallback when domain_hint gives no match. Invalid output is
    retried once, then falls back to "custom" (CLAUDE.md stage 2 rule)."""
    valid_codes = {a.catalog_code for a in catalog.actions} | {CUSTOM_CATALOG_CODE}
    payload = {
        "raw_text": raw_text,
        "candidates": [
            {
                "catalog_code": a.catalog_code,
                "name_ko": a.name_ko,
                "domain": a.domain,
                "atomic_behaviors": a.atomic_behaviors if isinstance(a.atomic_behaviors, list) else [],
            }
            for a in catalog.actions
        ],
    }
    for _ in range(2):
        result = _valid_classification(llm_provider.generate_json("classify_action_directive", payload), valid_codes)
        if result is not None:
            return result.catalog_code
    return CUSTOM_CATALOG_CODE


def _scalar_target(action: CatalogAction) -> Optional[CatalogTarget]:
    # H1 splits its target into named sub-targets; which one applies is a
    # clinician choice, so the normalizer does not pick.
    target = action.default_target
    return target if isinstance(target, CatalogTarget) else None


def parse_target_hint(target_hint: Optional[str], action: CatalogAction) -> Optional[ActionTarget]:
    default = _scalar_target(action)
    if not target_hint or default is None or TODO_CLINICIAN in (default.unit, default.comparator):
        return None
    pattern = _TARGET_PATTERNS.get(str(default.unit))
    match = pattern.search(target_hint) if pattern else None
    if match is None:
        return None
    numbers = [int(g) for g in match.groups() if g is not None]
    value = numbers[0] * numbers[1] if len(numbers) == 2 else numbers[0]
    return ActionTarget(value=value, unit=default.unit, comparator=default.comparator)


def catalog_default_target(action: CatalogAction) -> Optional[ActionTarget]:
    default = _scalar_target(action)
    if default is None or TODO_CLINICIAN in (default.value, default.unit, default.comparator):
        return None
    return ActionTarget(value=default.value, unit=default.unit, comparator=default.comparator)


def normalize_directive(
    directive: ActionDirective,
    catalog: Catalog,
    plan_id: str,
    action_id: str,
    llm_provider: LLMProvider,
) -> ActionItem:
    code = match_by_domain(directive.domain_hint, catalog)
    matched_by_llm = code is None
    if code is None:
        code = classify_with_llm(directive.raw_text, catalog, llm_provider)
    action = next((a for a in catalog.actions if a.catalog_code == code), None)
    target = None
    if action is not None:
        target = parse_target_hint(directive.target_hint, action) or catalog_default_target(action)
    needs_review = directive.needs_review or matched_by_llm or code == CUSTOM_CATALOG_CODE or target is None
    return ActionItem(
        action_id=action_id,
        plan_id=plan_id,
        catalog_code=code,
        target=target,
        source_directive_id=directive.directive_id,
        status=ActionStatus.DRAFT,
        needs_review=needs_review,
    )


def normalize_directives(
    directives: list[ActionDirective],
    catalog: Catalog,
    plan_id: str,
    llm_provider: LLMProvider,
) -> list[ActionItem]:
    return [
        normalize_directive(d, catalog, plan_id, f"A-{i + 1:03d}", llm_provider)
        for i, d in enumerate(directives)
    ]

"""Non-adherence reason collection (docs/ARIAD_stage2_design.md Part 3-3·3-4, Step 5).

Order is fixed:

1. Red flag rules (config/red_flags.yaml) run first on the free text and
   any measured value. A hit skips classification entirely: the report
   carries red_flag=true, the matched categories, the guidance text and a
   clinician alert. These are keyword/number rules, never the LLM.
2. A reason the respondent picked from the offered options is used as is.
3. Otherwise the LLM maps the free text to one of the ten Part 3-3 codes
   with a confidence. Invalid output is retried once; still invalid or
   "no basis" -> stored unclassified with needs_review. Confidence below
   config/barrier.yaml min_confidence adds one follow-up question.

free_text is patient-written: it is stored on the report but never logged.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import ValidationError

from app.domain.stage2 import (
    BarrierClassification,
    BarrierCode,
    BarrierConfig,
    BarrierReport,
    RedFlagRules,
)
from app.providers.base import LLMProvider


def detect_red_flags(
    free_text: Optional[str],
    rules: RedFlagRules,
    measured_values: Optional[dict[str, float]] = None,
) -> list[str]:
    """Matched category keys, in config order. measured_values maps a
    category key (e.g. "hypoglycemia") to a device/entered number checked
    against that category's numeric threshold."""
    text = free_text or ""
    measured_values = measured_values or {}
    hits = []
    for key, category in rules.categories.items():
        matched = any(re.search(pattern, text) for pattern in category.patterns)
        if not matched and category.numeric is not None:
            numbers = [float(m.group(1)) for m in re.finditer(category.numeric.value_pattern, text)]
            if key in measured_values:
                numbers.append(measured_values[key])
            matched = any(n < category.numeric.lt for n in numbers)
        if matched:
            hits.append(key)
    return hits


def _valid_classification(raw: dict) -> Optional[BarrierClassification]:
    try:
        result = BarrierClassification.model_validate(raw)
    except ValidationError:
        return None
    if result.code is not None and result.code not in {c.value for c in BarrierCode}:
        return None
    if not 0.0 <= result.confidence <= 1.0:
        return None
    return result


def classify_free_text(
    free_text: str, llm_provider: LLMProvider, config: BarrierConfig
) -> tuple[Optional[BarrierCode], Optional[float]]:
    payload = {
        "free_text": free_text,
        "codes": [{"code": code.value, "label_ko": info.label_ko} for code, info in config.codes.items()],
    }
    for _ in range(2):  # CLAUDE.md stage 2 rule: retry invalid LLM output once
        result = _valid_classification(llm_provider.generate_json("classify_barrier", payload))
        if result is not None:
            if result.code is None:
                return None, result.confidence
            return BarrierCode(result.code), result.confidence
    return None, None


def build_barrier_report(
    action_id: str,
    week: str,
    *,
    llm_provider: LLMProvider,
    rules: RedFlagRules,
    config: BarrierConfig,
    free_text: Optional[str] = None,
    selected_code: Optional[BarrierCode] = None,
    measured_values: Optional[dict[str, float]] = None,
) -> BarrierReport:
    red_flags = detect_red_flags(free_text, rules, measured_values)
    if red_flags:
        return BarrierReport(
            action_id=action_id,
            week=week,
            free_text=free_text,
            red_flag=True,
            red_flag_categories=red_flags,
            guidance_text=rules.guidance_template,
            notify_clinician=True,
            needs_review=True,
        )
    if selected_code is not None:
        return BarrierReport(action_id=action_id, week=week, code=selected_code, free_text=free_text)
    if not free_text or not free_text.strip():
        raise ValueError("a barrier report needs a selected code or free text")

    code, confidence = classify_free_text(free_text, llm_provider, config)
    if code is None:
        return BarrierReport(
            action_id=action_id,
            week=week,
            free_text=free_text,
            classifier_confidence=confidence,
            follow_up_question=config.unclassified_follow_up,
            needs_review=True,
        )
    low = confidence < config.min_confidence
    return BarrierReport(
        action_id=action_id,
        week=week,
        code=code,
        free_text=free_text,
        classifier_confidence=confidence,
        follow_up_question=config.follow_up_template.format(label_ko=config.codes[code].label_ko) if low else None,
        needs_review=low,
    )

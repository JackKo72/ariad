"""validate_grounding pipeline stage (docs/ARCHITECTURE.md section 5).

Checks every clinician-facing explanation sentence appears verbatim in the
source transcript. This is what actually enforces the "입력에 없는 진단·약물·
용량·수치·날짜를 생성하지 않는다" rule once a clinician has hand-edited the
mock draft -- the mock provider itself only ever copies transcript text, so
this only fires on edited content.
"""

from __future__ import annotations

from app.domain.models import ExplanationDraft, ValidationReport

_CHECKED_FIELDS = (
    "current_situation",
    "tests_and_reasons",
    "treatment_plan",
    "medication_instructions",
    "warning_signs",
    "what_to_do_next",
    "follow_up",
    "items_to_confirm_with_clinician",
)


def validate_grounding(explanation: ExplanationDraft, source_transcript_text: str) -> ValidationReport:
    issues: list[str] = []
    for field in _CHECKED_FIELDS:
        for item in getattr(explanation, field):
            item_text = item.strip()
            if item_text and item_text not in source_transcript_text:
                preview = item_text[:60]
                issues.append(f"{field}: '{preview}' is not grounded in the source transcript")
    return ValidationReport(valid=len(issues) == 0, issues=issues)

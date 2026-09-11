"""Unit: validate_grounding must catch clinician-introduced unsupported claims."""

from app.domain.models import ExplanationDraft
from app.pipeline.validation import validate_grounding

SOURCE = "의사: 혈압약 5mg 하루 한 번 복용하세요."


def test_grounded_explanation_is_valid():
    draft = ExplanationDraft(medication_instructions=["의사: 혈압약 5mg 하루 한 번 복용하세요."])
    report = validate_grounding(draft, SOURCE)
    assert report.valid
    assert report.issues == []


def test_unsupported_claim_is_flagged():
    draft = ExplanationDraft(medication_instructions=["혈압약 10mg 하루 두 번 복용하세요"])
    report = validate_grounding(draft, SOURCE)
    assert not report.valid
    assert "medication_instructions" in report.issues[0]


def test_draft_notice_is_never_checked_against_source():
    draft = ExplanationDraft(draft_notice="의료진 검토 전 초안입니다.")
    report = validate_grounding(draft, SOURCE)
    assert report.valid

"""Grounding check for ClinicalStructure.action_directives (Step 3).

Same idea as enrichment_validation.py: mechanically verify that what the
LLM says it copied really is in the input segments. A directive that fails
any check is kept (the clinician still sees it) but forced to
needs_review=true; one that passes keeps the LLM's own needs_review value.
Issue strings name only IDs and check names, never transcript text, so they
are safe to count or log (docs/DEBUGGING.md).
"""

from __future__ import annotations

import re

from app.domain.models import ActionDirective, SourceSpan
from app.pipeline.segments import Segment

_DIGITS_RE = re.compile(r"\d+")
_RESPONDER_ROLES = {"patient", "guardian"}


def _span_issues(spans: list[SourceSpan], by_id: dict[str, Segment], allowed_roles: set[str], where: str) -> list[str]:
    if not spans:
        return [f"{where}: no source_spans"]
    issues = []
    for span in spans:
        seg = by_id.get(span.segment_id)
        if seg is None:
            issues.append(f"{where}: unknown segment_id {span.segment_id}")
            continue
        if not span.quote or span.quote not in seg["text"]:
            issues.append(f"{where}: quote not in {span.segment_id}")
        if span.role != seg["role"] or span.speaker != seg["speaker"]:
            issues.append(f"{where}: speaker/role tag differs from {span.segment_id}")
        if seg["role"] not in allowed_roles:
            issues.append(f"{where}: {span.segment_id} role {seg['role']} not in {sorted(allowed_roles)}")
    return issues


def _text_in_spans(text: str, spans: list[SourceSpan], by_id: dict[str, Segment]) -> bool:
    texts = [by_id[s.segment_id]["text"] for s in spans if s.segment_id in by_id]
    return any(text in t for t in texts) or text in " ".join(texts)


def directive_issues(directive: ActionDirective, segments: list[Segment]) -> list[str]:
    by_id = {seg["id"]: seg for seg in segments}
    did = directive.directive_id
    issues = _span_issues(directive.source_spans, by_id, {"doctor"}, did)
    if not _text_in_spans(directive.raw_text, directive.source_spans, by_id):
        issues.append(f"{did}: raw_text not verbatim in its segments")
    if directive.target_hint:
        # 입력에 없는 수치 생성 금지: every number in the hint must be spoken.
        missing = [n for n in _DIGITS_RE.findall(directive.target_hint) if n not in directive.raw_text]
        if missing:
            issues.append(f"{did}: target_hint number not in raw_text")
    response = directive.patient_response
    if response is not None:
        issues += _span_issues(response.source_spans, by_id, _RESPONDER_ROLES, f"{did}.patient_response")
        if not _text_in_spans(response.text, response.source_spans, by_id):
            issues.append(f"{did}.patient_response: text not verbatim")
    for i, barrier in enumerate(directive.barrier_mentions):
        where = f"{did}.barrier_mentions[{i}]"
        issues += _span_issues(barrier.source_spans, by_id, _RESPONDER_ROLES, where)
        if not _text_in_spans(barrier.text, barrier.source_spans, by_id):
            issues.append(f"{where}: text not verbatim")
    return issues


def validate_action_directives(directives: list[ActionDirective], segments: list[Segment]) -> list[ActionDirective]:
    return [
        d.model_copy(update={"needs_review": True}) if directive_issues(d, segments) else d
        for d in directives
    ]

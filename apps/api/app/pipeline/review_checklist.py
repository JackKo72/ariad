"""Clinician review checklist (tasks/10_CLINICAL_FRAME_AND_REVIEW.md).

Keyword evals cannot tell "clopi loading 함" from "clopi loading 안 함", and
an LLM can silently flip a negative decision. So the items where a flip or a
guess does the most harm are listed for explicit clinician sign-off, and
approval is refused until every listed id is acknowledged (routes/
encounters.py approve). Items:
  - decisions that are not a plain "do it" (decided_not_to_do, conditional,
    undecided) or that the LLM itself flagged needs_confirmation
  - term candidates with risk "inference" (suspected diagnosis/procedure).
    "exam" candidates (exam/observation records) are shown but need no
    sign-off -- tasks/12, clinician decision, to keep the list short.
  - medications flagged needs_confirmation
Ids hash the item's content: editing an item changes its id, so an
acknowledgment given before the edit no longer counts.
"""

from __future__ import annotations

import hashlib
import json

from app.domain.models import ClinicalStructure, ReviewItem

_DECISION_STATUS_KO = {
    "decided_to_do": "시행",
    "decided_not_to_do": "하지 않음",
    "conditional": "조건부",
    "undecided": "미결정",
}


def _item_id(kind: str, content: dict) -> str:
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return f"{kind}:{digest[:12]}"


def build_review_checklist(structure: ClinicalStructure) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for d in structure.decisions:
        if d.status == "decided_to_do" and not d.needs_confirmation:
            continue
        text = f"[{_DECISION_STATUS_KO[d.status]}] {d.text}"
        if d.condition:
            text += f" (조건: {d.condition})"
        items.append(ReviewItem(id=_item_id("decision", d.model_dump()), kind="decision", text=text,
                                source_segment_ids=d.source_segment_ids))
    for c in structure.term_candidates:
        if c.risk != "inference":
            continue
        items.append(ReviewItem(id=_item_id("term_candidate", c.model_dump()), kind="term_candidate",
                                text=f'"{c.spoken_text}" → {c.term} (용어 후보, {c.frame})',
                                source_segment_ids=c.source_segment_ids))
    for m in structure.medications:
        if not m.needs_confirmation:
            continue
        items.append(ReviewItem(id=_item_id("medication", m.model_dump()), kind="medication",
                                text=f"{m.name} {m.dose} {m.frequency} ({m.action})".replace("  ", " ").strip(),
                                source_segment_ids=m.source_segment_ids))
    return items


def missing_acknowledgments(structure: ClinicalStructure, acknowledged_ids: list[str]) -> list[ReviewItem]:
    acknowledged = set(acknowledged_ids)
    return [item for item in build_review_checklist(structure) if item.id not in acknowledged]

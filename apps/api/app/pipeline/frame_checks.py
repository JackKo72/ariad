"""Disease must-check lists (tasks/14_FRAME_MUST_CHECK.md).

A frame may have prompts/frame_checks/<frame>.json: what an encounter for
that disease should cover (onset time for stroke, provoking factors for a
seizure...). The frame_checklist call marks each item mentioned -- with a
verbatim quote -- or not_mentioned. This module enforces the list:
  - the result is always the whole list, in list order, labels from the file
    (unknown ids from the LLM are dropped, missing ones are not_mentioned),
  - a mentioned item whose quote is not in the transcript is not_mentioned:
    the model cannot claim coverage the transcript does not show.
not_mentioned is information for the clinician, never a gap the model fills.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from app.domain.models import ClinicalFrameId, FrameCheckItem, FrameCheckList
from app.observability import StageTimer
from app.providers.base import LLMProvider

logger = logging.getLogger("ariad.pipeline")

CHECKS_DIR = Path(__file__).resolve().parents[4] / "prompts" / "frame_checks"


@lru_cache(maxsize=None)
def load_frame_checks(frame_id: ClinicalFrameId) -> Optional[dict[str, Any]]:
    """The must-check list for a frame, or None if it has none. Cached:
    callers must not mutate it."""
    path = CHECKS_DIR / f"{frame_id}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"frame": data["frame"], "items": data["items"]}


def check_frame_items(
    transcript_text: str,
    llm_provider: LLMProvider,
    frame_id: ClinicalFrameId,
    stage_timer: Optional[StageTimer] = None,
) -> list[FrameCheckItem]:
    checklist = load_frame_checks(frame_id)
    if checklist is None:
        return []
    raw = llm_provider.generate_json(
        "frame_checklist", {"transcript_text": transcript_text, "checklist": checklist}, stage_timer=stage_timer
    )
    return validate_frame_checks(FrameCheckList.model_validate(raw).items, checklist, transcript_text)


def validate_frame_checks(
    found: list[FrameCheckItem], checklist: dict[str, Any], transcript_text: str
) -> list[FrameCheckItem]:
    by_id: dict[str, FrameCheckItem] = {}
    for item in found:
        by_id.setdefault(item.id, item)
    transcript = "".join(transcript_text.split())
    result, downgraded = [], 0
    for spec in checklist["items"]:
        item = by_id.get(spec["id"])
        quote = item.spoken_text.strip() if item else ""
        if item is not None and item.status == "mentioned" and quote and "".join(quote.split()) in transcript:
            result.append(FrameCheckItem(id=spec["id"], label=spec["label"], status="mentioned",
                                         spoken_text=quote, source_segment_ids=item.source_segment_ids))
            continue
        if item is not None and item.status == "mentioned":
            downgraded += 1
        result.append(FrameCheckItem(id=spec["id"], label=spec["label"]))
    if downgraded:
        # Counts only -- never the quote (docs/DEBUGGING.md).
        logger.info("frame_checks without a verbatim quote set to not_mentioned: %d", downgraded)
    return result

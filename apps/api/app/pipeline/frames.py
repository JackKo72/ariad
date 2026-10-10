"""Clinical frame vocabularies and term-candidate validation
(tasks/10_CLINICAL_FRAME_AND_REVIEW.md).

A clinical frame (stroke, seizure) is clinician-provided context: picking it
is what allows a lay phrase ("혈관 안으로 관을 넣어 혈전을 빼내는 시술") to be
offered as a clinical term (EVT). Without it, or outside its vocabulary,
that mapping would be a term the transcript never contained -- CLAUDE.md
forbids generating those. So the LLM may only propose `term_candidates`,
and this module mechanically drops any candidate that:
  - names a frame other than the selected one (or no frame was selected),
  - uses a term not in that frame's vocabulary (prompts/frames/<id>.json),
    and sets each kept candidate's `risk` from the vocabulary (tasks/12),
  - quotes `spoken_text` that is not actually in the transcript.
Every surviving candidate still goes to clinician review
(app/pipeline/review_checklist.py).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from app.domain.models import ClinicalFrameId, ClinicalStructure

logger = logging.getLogger("ariad.pipeline")

FRAMES_DIR = Path(__file__).resolve().parents[4] / "prompts" / "frames"
# Vocabularies shared by several frames (e.g. the neurologic exam), pulled in
# through a frame's "includes" -- never selectable on their own.
SHARED_DIR = FRAMES_DIR / "shared"


@lru_cache(maxsize=None)
def load_frame(frame_id: ClinicalFrameId) -> dict[str, Any]:
    """The frame file with its `includes` merged in (rules appended, terms
    de-duplicated by name, frame's own terms first) -- this merged dict is
    also exactly what the LLM receives. Cached: callers must not mutate it."""
    frame = json.loads((FRAMES_DIR / f"{frame_id}.json").read_text(encoding="utf-8"))
    rules, terms = list(frame.get("rules", [])), list(frame.get("terms", []))
    seen = {t["term"] for t in terms}
    for name in frame.get("includes", []):
        shared = json.loads((SHARED_DIR / f"{name}.json").read_text(encoding="utf-8"))
        rules += shared.get("rules", [])
        for term in shared["terms"]:
            if term["term"] not in seen:
                seen.add(term["term"])
                terms.append(term)
    merged = {k: v for k, v in frame.items() if k not in ("includes", "note")}
    return {**merged, "rules": rules, "terms": terms}


def _norm(text: str) -> str:
    return "".join(text.split())


def validate_term_candidates(
    structure: ClinicalStructure, frame_id: Optional[ClinicalFrameId], transcript_text: str
) -> ClinicalStructure:
    if not structure.term_candidates:
        return structure
    risk_of = {t["term"]: t["risk"] for t in load_frame(frame_id)["terms"]} if frame_id else {}
    transcript = _norm(transcript_text)
    kept = [
        # tasks/12: risk comes from the vocabulary, whatever the LLM said.
        c.model_copy(update={"risk": risk_of[c.term]})
        for c in structure.term_candidates
        if frame_id is not None
        and c.frame == frame_id
        and c.term in risk_of
        and c.spoken_text.strip()
        and _norm(c.spoken_text) in transcript
    ]
    dropped = len(structure.term_candidates) - len(kept)
    if dropped:
        # Counts only -- never the candidate text (docs/DEBUGGING.md).
        logger.info("term_candidates dropped by frame validation: %d of %d", dropped, len(structure.term_candidates))
    return structure.model_copy(update={"term_candidates": kept})

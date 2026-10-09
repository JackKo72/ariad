#!/usr/bin/env python3
"""`ANSWER=data/annotations/sim_icu_01.answer.txt make answer-to-transcript`

tasks/09_STRUCTURE_EVAL_AGAINST_CLINICIAN_GOLD.md: a clinician's typed
answer transcript of a role-played recording (no timestamps) ->
<stem>.transcript.json segments {id, speaker, expected_role, text}, the
"oracle ASR" input for scripts/eval_structure_against_gold.py (structuring
quality measured without ASR/diarization error).

Answer format, as typed by hand: a line starting with a role word switches
speaker ("의사: ...", "보호자 ...", "보호자:" alone on a line); every other
non-empty line continues the current speaker. One line = one segment.
Only a colon is unambiguous: "의사 근데..." is a speaker switch but "환자 상태
설명 드리려고" is the doctor talking ABOUT the patient -- same shape. So every
switch without a colon is reported for a human check, and SPEAKERS limits
which role words can switch at all (e.g. SPEAKERS=의사,보호자 for an ICU talk
with an intubated patient).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROLES = {"의사": ("DOC", "doctor"), "보호자": ("GUARD", "guardian"), "환자": ("PT", "patient"),
         "간호사": ("STAFF", "staff")}


def parse_answer(text: str, speakers: tuple[str, ...] = tuple(ROLES)) -> tuple[list[dict], list[str]]:
    """Returns (segments, warnings). `speakers`: role words allowed to switch."""
    # "환자분", "보호자님" are content (address forms), never a speaker switch.
    role_re = re.compile(rf"^({'|'.join(speakers)})(?![분님])(\s*[:：]\s*|\s+|)(.*)$")
    segments, warnings = [], []
    speaker = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        match = role_re.match(line)
        if match:
            speaker = match.group(1)
            if ":" not in match.group(2) and "：" not in match.group(2) and match.group(3):
                warnings.append(f"line {lineno}: no colon after {speaker!r} -- read as {speaker} speaking, check")
            line = match.group(3).strip()
            if not line:
                continue
        if speaker is None:
            warnings.append(f"line {lineno}: text before any speaker label -- skipped")
            continue
        code, role = ROLES[speaker]
        segments.append({"id": f"seg_{len(segments) + 1:03d}", "speaker": code, "expected_role": role, "text": line})
    return segments, warnings


def main() -> int:
    answer = os.environ.get("ANSWER")
    if not answer or not Path(answer).exists():
        print("Usage: ANSWER=path/to/answer.txt python3 scripts/answer_to_transcript.py")
        return 1
    answer_path = Path(answer)
    speakers = tuple(s.strip() for s in os.environ.get("SPEAKERS", ",".join(ROLES)).split(","))
    unknown = [s for s in speakers if s not in ROLES]
    if unknown:
        print(f"Unknown SPEAKERS {unknown}; allowed: {', '.join(ROLES)}")
        return 1
    segments, warnings = parse_answer(answer_path.read_text(encoding="utf-8"), speakers)
    for warning in warnings:
        print(f"  warning: {warning}")
    stem = answer_path.name.split(".")[0]
    out_path = Path(os.environ.get("OUT", answer_path.with_name(f"{stem}.transcript.json")))
    out_path.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
    counts: dict[str, int] = {}
    for seg in segments:
        counts[seg["speaker"]] = counts.get(seg["speaker"], 0) + 1
    print(f"{len(segments)} segments {counts} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

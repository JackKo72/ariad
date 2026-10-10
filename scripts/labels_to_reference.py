#!/usr/bin/env python3
"""`LABELS=data/annotations/icu.labels.txt make labels-to-reference`

tasks/08_REAL_VOICE_REFERENCE_ANNOTATION.md step 2: a clinician-corrected
Audacity label export (`start<TAB>end<TAB>SPEAKER|TYPE|text`, drafted by
scripts/draft_reference_annotation.py) -> <stem>.ref.json next to it, the
format `make eval-diarization-der` (SET_DIR auto-discovery) and
`make noisy-diarization-set` (CLEAN_GT=) both read.

SPEAKER: DOC, DOC2.., PT, GUARD, GUARD2.., STAFF, STAFF2.., BG1, BG2..
  (BG* = not part of this encounter: neighbouring bed, PA system, passer-by
  -- one label per distinct voice, so an engine that separates them is not
  scored as confused). TYPE: exam / order / explain / other.
  Overlapping regions are allowed (overlapped speech).

Every problem line is reported with its line number and nothing is written
until the whole file is valid -- a half-wrong reference silently skews DER.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

SPEAKER_RE = re.compile(r"^(DOC|PT|GUARD|STAFF)\d*$|^BG\d+$")
ROLE_BY_PREFIX = {"DOC": "doctor", "PT": "patient", "GUARD": "guardian", "STAFF": "staff", "BG": "background"}
TYPES = {"exam", "order", "explain", "other"}


def parse_labels(text: str) -> tuple[list[dict], list[str]]:
    """Returns (segments, errors). Segments are sorted by start time."""
    segments, errors = [], []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.startswith("\\"):  # "\" = Audacity frequency-range sub-line
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            errors.append(f"line {lineno}: expected start<TAB>end<TAB>label")
            continue
        try:
            start, end = float(fields[0]), float(fields[1])
        except ValueError:
            errors.append(f"line {lineno}: start/end are not numbers")
            continue
        parts = [p.strip() for p in fields[2].split("|", 2)]
        speaker = parts[0]
        discourse = parts[1] if len(parts) > 1 else ""
        if end <= start:
            errors.append(f"line {lineno}: end <= start (point label?)")
        if not SPEAKER_RE.match(speaker):
            errors.append(f"line {lineno}: speaker {speaker!r} is not DOC/PT/GUARD/STAFF[n] or BGn")
        if discourse not in TYPES:
            errors.append(f"line {lineno}: type {discourse!r} is not one of {sorted(TYPES)}")
        role = ROLE_BY_PREFIX[re.match(r"[A-Z]+", speaker).group()] if SPEAKER_RE.match(speaker) else ""
        segments.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "speaker": speaker,
            "background": role == "background",
            "expected_role": role,
            "discourse": discourse,
            "text": parts[2] if len(parts) > 2 else "",
        })
    if not segments and not errors:
        errors.append("no label regions found")
    return sorted(segments, key=lambda s: (s["start"], s["end"])), errors


def main() -> int:
    from env_paths import require_files

    paths = require_files(["LABELS"], "LABELS=path/to/corrected.txt python3 scripts/labels_to_reference.py")
    if paths is None:
        return 1
    labels_path = paths[0]
    segments, errors = parse_labels(labels_path.read_text(encoding="utf-8"))
    if errors:
        print(f"{len(errors)} problem(s), nothing written:")
        for error in errors:
            print(f"  {error}")
        return 1

    stem = labels_path.name.split(".")[0]
    out_path = Path(os.environ.get("OUT", labels_path.with_name(f"{stem}.ref.json")))
    out_path.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
    seconds: dict[str, float] = {}
    for seg in segments:
        seconds[seg["speaker"]] = seconds.get(seg["speaker"], 0.0) + seg["end"] - seg["start"]
    summary = " ".join(f"{spk}:{sec:.0f}s" for spk, sec in sorted(seconds.items()))
    print(f"{len(segments)} segments ({summary}) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

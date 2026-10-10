#!/usr/bin/env python3
"""`ANSWER=data/annotations/sim_icu_01.answer.txt make answer-to-transcript`

tasks/09_STRUCTURE_EVAL_AGAINST_CLINICIAN_GOLD.md: a clinician's typed
answer transcript of a role-played recording ->
<stem>.transcript.json segments {id, speaker, expected_role, text,
approx_start}, the "oracle ASR" input for scripts/eval_structure_against_gold.py
(structuring quality measured without ASR/diarization error).

Answer format, as typed by hand:
  - a line starting with a role word switches speaker: "의사: ...",
    "보호자 ...", "보호자:" alone, numbered "의사 1", "의사2", "간호사 2";
    "발화자 N" = speaker the annotator could not name (role unknown);
    "noise" = background speech, not part of this encounter
  - every other non-empty line continues the current speaker; one line =
    one segment
  - "(mm:ss)" anywhere on a line is a timestamp, removed from the text and
    kept as approx_start (seconds) for the segments that follow
  - a line starting with "--" is a comment; if it says "N분 M초" (e.g. "--
    여기서부터 두번째 녹음, 첫녹음 6분 1초") later timestamps are offset by
    that much -- two recordings joined into one audio file
Only a colon is unambiguous: "의사 근데..." is a speaker switch but "환자 상태
설명 드리려고" is the doctor talking ABOUT the patient -- same shape. So every
switch without a colon is reported for a human check, and SPEAKERS limits
which role words can switch at all (e.g. SPEAKERS=의사,보호자 for an ICU talk
with an intubated patient). ALIASES="발화자 1=의사 1" renames a speaker once
the annotator knows who it was.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# role word -> (speaker code prefix, expected_role)
ROLES = {"의사": ("DOC", "doctor"), "보호자": ("GUARD", "guardian"), "환자": ("PT", "patient"),
         "간호사": ("STAFF", "staff"), "발화자": ("SPK", "unknown"), "noise": ("BG", "background")}
TIMESTAMP_RE = re.compile(r"\((\d{1,2}):(\d{2})\)")
OFFSET_RE = re.compile(r"(\d+)\s*분\s*(\d+)\s*초")


def speaker_code(word: str, number: str) -> str:
    """의사/의사 1 -> DOC, 의사 2 -> DOC2; 발화자 N always keeps N; noise -> BG1."""
    prefix = ROLES[word][0]
    if word == "발화자":
        return f"{prefix}{number or 1}"
    if word == "noise":
        return "BG1"
    return prefix if number in ("", "1") else f"{prefix}{number}"


def parse_answer(text: str, speakers: tuple[str, ...] = tuple(ROLES),
                 aliases: dict[str, str] | None = None) -> tuple[list[dict], list[str]]:
    """Returns (segments, warnings). `speakers`: role words allowed to switch;
    `aliases`: "발화자 1" -> "의사 1" style renames (spacing-insensitive)."""
    aliases = {"".join(k.split()): v for k, v in (aliases or {}).items()}
    # "환자분", "보호자님" are content (address forms), never a speaker switch.
    role_re = re.compile(rf"^({'|'.join(speakers)})(?:\s*(\d+))?(?![분님\d])(\s*[:：]\s*|\s+|)(.*)$", re.IGNORECASE)
    segments, warnings = [], []
    speaker = None
    offset = 0.0
    approx_start = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("--"):
            if match := OFFSET_RE.search(line):
                offset = int(match.group(1)) * 60 + int(match.group(2))
            continue
        if match := TIMESTAMP_RE.search(line):
            approx_start = offset + int(match.group(1)) * 60 + int(match.group(2))
            line = TIMESTAMP_RE.sub("", line).strip()
        match = role_re.match(line)
        if match:
            word, number = match.group(1).lower() if match.group(1).isascii() else match.group(1), match.group(2) or ""
            if (alias := aliases.get(f"{word}{number}")) is not None:
                alias_match = role_re.match(alias)
                word, number = alias_match.group(1), alias_match.group(2) or ""
            speaker = (word, number)
            rest = match.group(4).strip()
            if ":" not in match.group(3) and "：" not in match.group(3) and rest:
                warnings.append(f"line {lineno}: no colon after {match.group(1)!r} -- read as a speaker switch, check")
            if word == "발화자":
                warnings.append(f"line {lineno}: unnamed speaker {word} {number or 1} -- role unknown (ALIASES= to name)")
            line = rest
            if not line:
                continue
        if speaker is None:
            warnings.append(f"line {lineno}: text before any speaker label -- skipped")
            continue
        word, number = speaker
        segments.append({
            "id": f"seg_{len(segments) + 1:03d}",
            "speaker": speaker_code(word, number),
            "expected_role": ROLES[word][1],
            "text": line,
            "approx_start": approx_start,
        })
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
    aliases = dict(pair.split("=", 1) for pair in os.environ.get("ALIASES", "").split(",") if "=" in pair)
    segments, warnings = parse_answer(answer_path.read_text(encoding="utf-8"), speakers, aliases)
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

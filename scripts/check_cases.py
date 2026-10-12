#!/usr/bin/env python3
"""`make check-cases [CASE=er_3023432]`

tasks/16: one line per case folder (apps/api/data/cases/, see scripts/cases.py)
saying which files are there, whether meta.json is valid, which gold it is
scored against, and whether the EMR / answer / meta files still contain
anything identifying (resident number, phone, calendar date, long ID,
email, name field) -- by line number only.

Prints names, counts and line numbers, never file contents, so the output
can be pasted into a chat for review.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import (  # noqa: E402
    CASE_ID,
    CASES_DIR,
    anonymization_flags,
    case_file,
    find_audio,
    gold_path,
    load_meta,
    validate_meta,
)


def _duration(path: Path) -> str:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(path)], capture_output=True, text=True, timeout=30).stdout.strip()
        seconds = float(out)
        return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"
    except (OSError, ValueError, subprocess.SubprocessError):
        return "?"


def check(case: str) -> int:
    problems = 0
    print(f"\n[{case}]")
    if not CASE_ID.match(case):
        print("  ! folder name should be <er|icu|ward|opd>_<number>, e.g. er_3023432")
        problems += 1
    audio, opus = find_audio(case), case_file(case, ".opus")
    print(f"  audio      {audio.name + ' ' + _duration(audio) if audio else 'MISSING'}"
          f"{'  | prepared .opus ok' if opus.is_file() else '  | no .opus yet: make prepare-case-audio CASE=' + case}")
    for suffix, label, hint in ((".answer.txt", "answer", "clinician answer transcript"),
                                (".transcript.json", "transcript", f"make answer-to-transcript ANSWER=<{case}.answer.txt>"),
                                (".emr.txt", "emr", "optional: anonymized chart, gold reference only")):
        path = case_file(case, suffix)
        if path.is_file():
            extra = ""
            if suffix == ".transcript.json":
                extra = f" ({len(json.loads(path.read_text(encoding='utf-8'))['segments'])} segments)"
            else:
                extra = f" ({len(path.read_text(encoding='utf-8').splitlines())} lines)"
            print(f"  {label:<11}ok{extra}")
        else:
            print(f"  {label:<11}- ({hint})")
    meta = load_meta(case)
    if meta is None:
        print(f"  meta       MISSING ({case}.meta.json -- see docs/CASE_DATA.md)")
        problems += 1
    else:
        issues = validate_meta(case, meta)
        problems += len(issues)
        # recorded_at is relative time ("D0 ER 도착 +2h"); shown only when the meta
        # file has nothing that looks identifying, so the output stays pasteable.
        meta_text = case_file(case, ".meta.json").read_text(encoding="utf-8")
        clean = not anonymization_flags(meta_text, (case.split("_", 1)[-1],))
        recorded = (meta.get("recorded_at") or "-") if clean else "(hidden: fix the flags below)"
        print(f"  meta       setting={meta.get('setting')} frame={meta.get('frame') or '-'} "
              f"split={meta.get('split')} gold_case={meta.get('gold_case') or '-'}")
        print(f"  recorded   {recorded}")
        for issue in issues:
            print(f"  ! meta: {issue}")
    gold = gold_path(case, meta)
    print(f"  gold       {gold.name if gold.is_file() else 'none yet (' + gold.name + ')'}")
    number = case.split("_", 1)[-1]
    for suffix in (".emr.txt", ".answer.txt", ".meta.json"):
        path = case_file(case, suffix)
        if not path.is_file():
            continue
        for kind, lines in anonymization_flags(path.read_text(encoding="utf-8"), (number,)).items():
            problems += 1
            shown = ", ".join(map(str, lines[:10])) + (" ..." if len(lines) > 10 else "")
            print(f"  ! {path.name}: possible {kind} on line {shown}")
    return problems


def main() -> int:
    if not CASES_DIR.is_dir():
        print(f"{CASES_DIR} does not exist yet -- create it and add one folder per recording (docs/CASE_DATA.md).")
        return 1
    only = os.environ.get("CASE")
    cases = [only] if only else sorted(p.name for p in CASES_DIR.iterdir() if p.is_dir())
    total = sum(check(case) for case in cases)
    print(f"\n{len(cases)} case(s) in {CASES_DIR}: {'OK' if total == 0 else f'{total} thing(s) to fix'}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())

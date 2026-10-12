#!/usr/bin/env python3
"""`make prepare-case-audio CASE=er_3023432`

tasks/16: converts the case's original recording (e.g. er_3023432.wma -- the
app's upload check does not accept WMA/ASF) to <case>.opus next to it:
mono, 16 kHz, 24 kbps Opus. Small enough to keep alongside the original,
and the format the earlier ER recording was analysed in. The original is
never modified. Prints names and duration only.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import case_dir, case_file, find_audio  # noqa: E402


def main() -> int:
    case = os.environ.get("CASE")
    if not case:
        print("CASE not set.\nUsage: make prepare-case-audio CASE=er_3023432")
        return 1
    if not case_dir(case).is_dir():
        print(f"{case_dir(case)} does not exist (docs/CASE_DATA.md)")
        return 1
    source, target = find_audio(case), case_file(case, ".opus")
    if source is None or source == target:
        print(f"no original recording named {case}.<wma|m4a|mp3|wav|...> in {case_dir(case)}")
        return 1
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-ac", "1", "-ar", "16000",
               "-c:a", "libopus", "-b:a", "24k", str(target)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg failed ({result.returncode}) converting {source.name}")
        return 1
    print(f"{source.name} -> {target.name} ({target.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

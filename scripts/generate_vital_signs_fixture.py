#!/usr/bin/env python3
"""Generates a synthetic vital-sign dictation fixture (tasks/06_ASR_OUTPUT_
VERIFICATION.md's "leading-keyword anchor" research step) using the same
offline TTS (espeak-ng) + ffmpeg approach as generate_sample_audio.py. A
separate fixture, not touching sample_consultation.wav or anything that
depends on it.

Purpose: the current post-ASR number normalizer (app/pipeline/
asr_normalize.py) only converts a number word when a unit word directly
follows it ("오 밀리그램" -> "5 밀리그램", a *trailing* anchor). The user
asked about the opposite case -- a domain keyword *before* the number
("혈압" implies the number that follows is a blood-pressure reading, a
*leading* anchor) -- and proposed running ASR on a few consultations to see
the real patterns before designing that rule. Real patient audio can't be
used for this (CLAUDE.md: synthetic data only), so this fixture covers
several leading-anchor shapes deliberately, to be run through
`make compare-asr-accuracy` on real hardware:

  - BP, bare number directly after the keyword, no trailing unit (혈압)
  - Weight, keyword AND a trailing unit both present (체중 ... 킬로그램)
  - Blood sugar, keyword several tokens away from the number (혈당 ... 검사 ...)
  - Pulse rate, trailing unit with a word in between (맥박은 분당 ... 회)
  - Two different vitals in one sentence -- the "ownership ambiguity" case
    that makes a naive "nearest keyword" rule unsafe
  - A decimal temperature (체온 ... 도) -- explicitly out of the current
    normalizer's scope (no decimal handling), included to see how the ASR
    model itself renders a decimal, not to be fixed by this fixture

Usage: python3 scripts/generate_vital_signs_fixture.py
   (not wired into `make sample-audio` -- a separate, additive fixture)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "tests" / "fixtures" / "audio"
GAP_SECONDS = 0.6
BASENAME = "vital_signs_dictation"

# (speaker label, expected clinical role, line, espeak-ng voice params,
#  vital-sign pattern this line demonstrates -- for the ground truth file
#  only, not spoken)
DIALOGUE = [
    ("A", "doctor", "오늘 혈압을 재보니 138에 86으로 나왔습니다.",
     {"speed": 150, "pitch": 35}, "bp_bare_number_leading_keyword"),
    ("B", "patient", "지난번보다 조금 높아진 것 같아요.",
     {"speed": 165, "pitch": 65}, "filler"),
    ("A", "doctor", "체중을 확인해보니 72킬로그램이네요.",
     {"speed": 150, "pitch": 35}, "weight_leading_and_trailing_unit"),
    ("B", "patient", "네, 요즘 운동을 못 해서요.",
     {"speed": 165, "pitch": 65}, "filler"),
    ("A", "doctor", "공복 혈당 검사를 했는데 수치가 118로 나왔습니다.",
     {"speed": 150, "pitch": 35}, "glucose_keyword_distant_from_number"),
    ("B", "patient", "식전에 뭘 좀 먹었나 봐요.",
     {"speed": 165, "pitch": 65}, "filler"),
    ("A", "doctor", "맥박은 분당 76회로 측정되었습니다.",
     {"speed": 150, "pitch": 35}, "pulse_trailing_unit_with_gap"),
    ("B", "patient", "네, 알겠습니다.",
     {"speed": 165, "pitch": 65}, "filler"),
    ("A", "doctor", "오늘은 혈압이 132에 84, 맥박은 70회였습니다.",
     {"speed": 150, "pitch": 35}, "two_vitals_one_sentence_ownership_ambiguity"),
    ("B", "patient", "조금 좋아졌네요.",
     {"speed": 165, "pitch": 65}, "filler"),
    ("A", "doctor", "체온을 재보니 37.5도였습니다.",
     {"speed": 150, "pitch": 35}, "temperature_decimal_out_of_scope"),
    ("B", "patient", "미열이 있었군요.",
     {"speed": 165, "pitch": 65}, "filler"),
]


def check_tools() -> None:
    missing = [t for t in ("espeak-ng", "ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        print(f"Missing required tool(s): {', '.join(missing)}")
        print("Install on Ubuntu with: sudo apt-get install -y ffmpeg espeak-ng")
        sys.exit(1)


def synth_segment(text: str, params: dict, out_path: Path) -> None:
    subprocess.run(
        ["espeak-ng", "-v", "ko", "-s", str(params["speed"]), "-p", str(params["pitch"]),
         "-w", str(out_path), text],
        check=True, capture_output=True,
    )


def make_silence(out_path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", str(seconds), str(out_path)],
        check=True, capture_output=True,
    )


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def build_audio(work_dir: Path) -> tuple[Path, list[dict]]:
    segments = []
    concat_paths = []
    cursor = 0.0

    for i, (speaker, role, text, params, pattern) in enumerate(DIALOGUE):
        seg_path = work_dir / f"seg_{i:02d}.wav"
        synth_segment(text, params, seg_path)
        duration = probe_duration(seg_path)
        segments.append(
            {
                "id": f"seg_{i + 1:03d}",
                "speaker": speaker,
                "expected_role": role,
                "start": round(cursor, 2),
                "end": round(cursor + duration, 2),
                "text": text,
                "vital_sign_pattern": pattern,
            }
        )
        concat_paths.append(seg_path)
        cursor += duration + GAP_SECONDS

        if i < len(DIALOGUE) - 1:
            gap_path = work_dir / f"gap_{i:02d}.wav"
            make_silence(gap_path, GAP_SECONDS)
            concat_paths.append(gap_path)

    list_file = work_dir / "concat_list.txt"
    with open(list_file, "w") as f:
        for p in concat_paths:
            f.write(f"file '{p.resolve()}'\n")

    final_wav = OUT_DIR / f"{BASENAME}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(final_wav)],
        check=True, capture_output=True,
    )
    return final_wav, segments


def main() -> None:
    check_tools()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = OUT_DIR / "_tmp_vital_signs_segments"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    try:
        final_wav, segments = build_audio(work_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    total_duration = probe_duration(final_wav)

    (OUT_DIR / f"{BASENAME}.transcript.json").write_text(
        json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"done -> {final_wav} ({total_duration:.1f}s), {len(segments)} segments")
    print(f"ground truth -> {OUT_DIR / f'{BASENAME}.transcript.json'}")
    print(
        "\nRun on real hardware with real sherpa-onnx models:\n"
        f"  AUDIO={final_wav.relative_to(REPO_ROOT)} "
        f"GROUND_TRUTH={(OUT_DIR / f'{BASENAME}.transcript.json').relative_to(REPO_ROOT)} "
        "make compare-asr-accuracy"
    )


if __name__ == "__main__":
    main()

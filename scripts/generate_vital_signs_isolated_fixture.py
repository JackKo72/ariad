#!/usr/bin/env python3
"""tasks/06_ASR_OUTPUT_VERIFICATION.md diagnostic: the real
`vital_signs_dictation.wav` run lost ALL FIVE vital-sign numbers entirely
(not merely garbled -- absent from the predicted text), while the older
sample_consultation.wav's one number instance ("145에 92로") came out
garbled-but-recognizable ("백사십오에구십이초금"). `espeak-ng -v ko -x`
(phoneme output, checked in this sandbox) confirms the TTS audio itself
pronounces every number correctly as Sino-Korean words ("138" ->
"백삼십팔", "86" -> "팔십육", "72" -> "칠십이") -- ruling out a TTS
mispronunciation artifact.

One real difference between the two fixtures: SherpaOnnxASRProvider's
merge_diarization_turns() caps a single decode pass at 28s
(max_segment_seconds), splitting anything longer into roughly-equal
pieces. Because this project's known diarization-merge limitation (see
README.md) collapses this fixture's whole recording into one giant turn
before that split, vital_signs_dictation.wav (53.34s) likely decoded as 2
chunks of ~26.7s each, while sample_consultation.wav (59.54s) decoded as 3
chunks of ~19.9s each -- i.e. the FAILED-numbers fixture had LONGER
single-pass decode chunks than the GARBLED-but-present-numbers one. That
correlation is suggestive, not proof (n=2).

This fixture tests that directly: each vital-sign line is synthesized with
a long silence gap (2.0s, deliberately > merge_diarization_turns'
merge_gap_seconds=0.8s default) so the known same-speaker-clustering bug
can no longer glue them back into one long turn regardless of how
diarization labels the speaker -- each line should decode as its own
short (a few seconds), isolated turn. If numbers come back once the
decode context is short, that points at long-context decode (or the
diarization-merge bug feeding it) as the real culprit, not a general
inability to recognize Korean numbers; if they still vanish, the problem
is independent of chunk length and something else (e.g. this specific
quantized model's handling of digit sequences) is at fault.

Usage: python3 scripts/generate_vital_signs_isolated_fixture.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "tests" / "fixtures" / "audio"
GAP_SECONDS = 2.0  # > merge_diarization_turns' merge_gap_seconds (0.8s)
BASENAME = "vital_signs_isolated"

# Same six vital-sign lines as generate_vital_signs_fixture.py's DIALOGUE,
# filler lines dropped -- this fixture isolates each number-bearing
# sentence, it doesn't need the surrounding conversation.
LINES = [
    ("오늘 혈압을 재보니 138에 86으로 나왔습니다.", "bp_bare_number_leading_keyword"),
    ("체중을 확인해보니 72킬로그램이네요.", "weight_leading_and_trailing_unit"),
    ("공복 혈당 검사를 했는데 수치가 118로 나왔습니다.", "glucose_keyword_distant_from_number"),
    ("맥박은 분당 76회로 측정되었습니다.", "pulse_trailing_unit_with_gap"),
    ("오늘은 혈압이 132에 84, 맥박은 70회였습니다.", "two_vitals_one_sentence_ownership_ambiguity"),
    ("체온을 재보니 37.5도였습니다.", "temperature_decimal_out_of_scope"),
]
VOICE_PARAMS = {"speed": 150, "pitch": 35}


def check_tools() -> None:
    missing = [t for t in ("espeak-ng", "ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        print(f"Missing required tool(s): {', '.join(missing)}")
        print("Install on Ubuntu with: sudo apt-get install -y ffmpeg espeak-ng")
        sys.exit(1)


def synth_segment(text: str, out_path: Path) -> None:
    subprocess.run(
        ["espeak-ng", "-v", "ko", "-s", str(VOICE_PARAMS["speed"]), "-p", str(VOICE_PARAMS["pitch"]),
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

    for i, (text, pattern) in enumerate(LINES):
        seg_path = work_dir / f"seg_{i:02d}.wav"
        synth_segment(text, seg_path)
        duration = probe_duration(seg_path)
        segments.append(
            {
                "id": f"seg_{i + 1:03d}",
                "speaker": "A",
                "expected_role": "doctor",
                "start": round(cursor, 2),
                "end": round(cursor + duration, 2),
                "text": text,
                "vital_sign_pattern": pattern,
            }
        )
        concat_paths.append(seg_path)
        cursor += duration + GAP_SECONDS

        if i < len(LINES) - 1:
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
    work_dir = OUT_DIR / "_tmp_vital_signs_isolated_segments"
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

    print(f"done -> {final_wav} ({total_duration:.1f}s), {len(segments)} segments, {GAP_SECONDS}s gaps")
    print(f"ground truth -> {OUT_DIR / f'{BASENAME}.transcript.json'}")
    print(
        "\nRun on real hardware with real sherpa-onnx models:\n"
        f"  AUDIO={final_wav.relative_to(REPO_ROOT)} "
        f"GROUND_TRUTH={(OUT_DIR / f'{BASENAME}.transcript.json').relative_to(REPO_ROOT)} "
        "make compare-asr-accuracy\n"
        "Also worth running `make diagnose-asr AUDIO=...` on this file to see the actual "
        "turn count/boundaries sherpa-onnx's diarizer produces here -- if it's still fewer "
        "than 6 turns despite the 2.0s gaps, the clustering bug is stronger than the gap-based "
        "merge guard and this test's premise (one short isolated turn per line) doesn't hold."
    )


if __name__ == "__main__":
    main()

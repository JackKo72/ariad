#!/usr/bin/env python3
"""Generates the demo-mode sample consultation fixture
(tasks/02_AUDIO_PIPELINE.md section 7) using offline TTS (espeak-ng) + ffmpeg.

No external API, no real patient voice. Two speakers (doctor/patient) get
distinct voice/pitch/speed so the sample is useful for testing diarization
UI even though the audio itself is synthetic. The dialogue deliberately
includes: a numeric vital (blood pressure), a medication name/dose/frequency
being started, a medication explicitly NOT started (negation), a follow-up
date, and an emergency-room warning sign, per the task's fixture checklist.

Usage: python3 scripts/generate_sample_audio.py   (invoked by `make sample-audio`)
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

# (speaker label, expected clinical role, line, espeak-ng voice params)
DIALOGUE = [
    ("A", "doctor", "안녕하세요. 오늘 혈압을 재보니 145에 92로 조금 높게 나왔습니다.",
     {"speed": 150, "pitch": 35}),
    ("B", "patient", "네, 요즘 좀 피곤하고 짜게 먹었던 것 같아요.",
     {"speed": 165, "pitch": 65}),
    ("A", "doctor", "그러시군요. 혈압약 리시노프릴 오 밀리그램을 하루 한 번 아침에 드시는 걸로 시작하겠습니다.",
     {"speed": 150, "pitch": 35}),
    ("B", "patient", "아스피린도 같이 먹어야 하나요?",
     {"speed": 165, "pitch": 65}),
    ("A", "doctor", "아니요, 아스피린은 지금 시작하지 않습니다. 출혈 위험이 있어서 필요하지 않은 상황이에요.",
     {"speed": 150, "pitch": 35}),
    ("B", "patient", "알겠습니다.",
     {"speed": 165, "pitch": 65}),
    ("A", "doctor", "그리고 이 주 뒤인 시월 첫째 주에 다시 오셔서 혈압을 확인하겠습니다.",
     {"speed": 150, "pitch": 35}),
    ("B", "patient", "네, 알겠습니다.",
     {"speed": 165, "pitch": 65}),
    ("A", "doctor", "만약 갑자기 심한 두통이나 가슴 통증, 숨쉬기 어려운 증상이 생기면 바로 응급실로 가셔야 합니다.",
     {"speed": 150, "pitch": 35}),
    ("B", "patient", "네, 명심하겠습니다.",
     {"speed": 165, "pitch": 65}),
]


def check_tools() -> None:
    missing = [t for t in ("espeak-ng", "ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        print(f"Missing required tool(s): {', '.join(missing)}")
        print("Install on Ubuntu with: sudo apt-get install -y ffmpeg espeak-ng")
        print("(this script does not run sudo itself)")
        sys.exit(1)


def synth_segment(text: str, params: dict, out_path: Path) -> None:
    subprocess.run(
        [
            "espeak-ng", "-v", "ko",
            "-s", str(params["speed"]), "-p", str(params["pitch"]),
            "-w", str(out_path), text,
        ],
        check=True, capture_output=True,
    )


def make_silence(out_path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", str(seconds), str(out_path)],
        check=True, capture_output=True,
    )


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def build_audio(work_dir: Path) -> tuple[Path, list[dict]]:
    segments = []
    concat_paths = []
    cursor = 0.0

    for i, (speaker, role, text, params) in enumerate(DIALOGUE):
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

    final_wav = OUT_DIR / "sample_consultation.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(final_wav),
        ],
        check=True, capture_output=True,
    )
    return final_wav, segments


def build_structure() -> dict:
    return {
        "problems": [
            {
                "text": "혈압이 145/92로 높게 측정됨",
                "certainty": "stated",
                "source_segment_ids": ["seg_001"],
            }
        ],
        "tests": [],
        "medications": [
            {
                "name": "리시노프릴",
                "dose": "5mg",
                "route": "경구",
                "frequency": "하루 한 번 아침",
                "action": "start",
                "source_segment_ids": ["seg_003"],
                "needs_confirmation": False,
            },
            {
                "name": "아스피린",
                "dose": "",
                "route": "",
                "frequency": "",
                "action": "stop",
                "source_segment_ids": ["seg_005"],
                "needs_confirmation": False,
            },
        ],
        "plan": [
            {
                "text": "2주 후 10월 첫째 주 재방문하여 혈압 확인",
                "source_segment_ids": ["seg_007"],
            }
        ],
        "warnings": [
            {
                "text": "심한 두통, 가슴 통증, 호흡곤란 발생 시 즉시 응급실 방문",
                "source_segment_ids": ["seg_009"],
            }
        ],
        "follow_up": [
            {
                "text": "10월 첫째 주 혈압 재확인",
                "source_segment_ids": ["seg_007"],
            }
        ],
        "questions_or_conflicts": [],
    }


def build_explanation() -> dict:
    # Every non-empty sentence below is a literal substring of one DIALOGUE
    # line (never paraphrased) so it satisfies validate_grounding's exact
    # substring check against the transcript derived from these same
    # segments -- the same "only ever copy source text" contract
    # MockLLMProvider upholds for the manual-transcript path (see
    # app/pipeline/validation.py). A real LLM provider (Phase D) may
    # legitimately paraphrase; this fixture intentionally does not, so the
    # demo path can reach APPROVED/PUBLISHED without weakening that check.
    return {
        "draft_notice": "의료진 검토 전 초안입니다.",
        "current_situation": ["오늘 혈압을 재보니 145에 92로 조금 높게 나왔습니다."],
        "tests_and_reasons": [],
        "treatment_plan": [
            "혈압약 리시노프릴 오 밀리그램을 하루 한 번 아침에 드시는 걸로 시작하겠습니다.",
            "아스피린은 지금 시작하지 않습니다.",
        ],
        "medication_instructions": ["혈압약 리시노프릴 오 밀리그램을 하루 한 번 아침에 드시는 걸로 시작하겠습니다."],
        "warning_signs": ["만약 갑자기 심한 두통이나 가슴 통증, 숨쉬기 어려운 증상이 생기면 바로 응급실로 가셔야 합니다."],
        "what_to_do_next": [],
        "follow_up": ["그리고 이 주 뒤인 시월 첫째 주에 다시 오셔서 혈압을 확인하겠습니다."],
        "items_to_confirm_with_clinician": [],
        "source_map": [
            {"field": "current_situation", "source_segment_ids": ["seg_001"]},
            {"field": "treatment_plan", "source_segment_ids": ["seg_003", "seg_005"]},
            {"field": "warning_signs", "source_segment_ids": ["seg_009"]},
            {"field": "follow_up", "source_segment_ids": ["seg_007"]},
        ],
    }


def main() -> None:
    check_tools()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = OUT_DIR / "_tmp_segments"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    try:
        final_wav, segments = build_audio(work_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    total_duration = probe_duration(final_wav)

    (OUT_DIR / "sample_consultation.transcript.json").write_text(
        json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "sample_consultation.structure.json").write_text(
        json.dumps(build_structure(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "sample_consultation.explanation.json").write_text(
        json.dumps(build_explanation(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"done -> {final_wav} ({total_duration:.1f}s), {len(segments)} segments")
    print(f"sidecar files written under {OUT_DIR}")


if __name__ == "__main__":
    main()

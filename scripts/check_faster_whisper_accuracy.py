#!/usr/bin/env python3
"""`apps/api/.venv/bin/python scripts/check_faster_whisper_accuracy.py`

tasks/05_ASR_HARDWARE_SPEEDUP.md: faster-whisper's raw decode speed
(RTF 0.02-0.03 on real hardware, see the task doc) must not be adopted on
speed alone -- this checks Korean clinical-transcription *accuracy* against
the same synthetic ground truth scripts/compare_asr_accuracy.py already
uses for the sherpa-onnx engine (medication name, dose, a negation, a
date), so the two engines can be compared on equal footing before either
becomes a real candidate.

Real clinical recordings (e.g. a user's own m4a file) must never have their
transcribed text printed or logged (docs/DEBUGGING.md, CLAUDE.md privacy
rules) -- this script only ever runs against the repo's own synthetic,
already-public sample_consultation.wav fixture, so printing its expected/
predicted text here is safe (same justification as compare_asr_accuracy.py).

Env vars: FASTER_WHISPER_MODEL (default "small"), FASTER_WHISPER_DEVICE
(default "cuda" if available else "cpu" -- pass explicitly to force),
FASTER_WHISPER_COMPUTE_TYPE (default "float16" for cuda, "int8" for cpu).

No speaker/diarization check here -- faster-whisper does ASR only, no
diarization (see tasks/05's explicit caveat about this). Opt-in, free
(no OpenAI call), never part of `make test`/`make e2e`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

DEFAULT_AUDIO = REPO_ROOT / "tests" / "fixtures" / "audio" / "sample_consultation.wav"
DEFAULT_GROUND_TRUTH = REPO_ROOT / "tests" / "fixtures" / "audio" / "sample_consultation.transcript.json"

# Same anchors as scripts/compare_asr_accuracy.py, for direct comparison.
ACCURACY_CHECKS = [
    {"segment_id": "seg_003", "label": "medication name (리시노프릴)", "keywords": ["리시노프릴"]},
    {"segment_id": "seg_003", "label": "dose (5mg)", "keywords": ["오밀리그램", "5밀리그램", "5mg"]},
    {
        "segment_id": "seg_005",
        "label": "negation (아스피린 미투여)",
        "keywords": ["않습니다", "않는", "않아"],
    },
    {"segment_id": "seg_007", "label": "date (시월 첫째 주)", "keywords": ["시월"]},
]


def _normalize(text: str) -> str:
    return text.replace(" ", "")


def _load_ground_truth(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["segments"]


def _overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _match_predicted_text(gt_segment: dict, predicted_segments: list) -> str:
    overlaps = [
        (
            _overlap_seconds(gt_segment["start"], gt_segment["end"], seg.start, seg.end),
            seg,
        )
        for seg in predicted_segments
    ]
    overlapping = [(ov, seg) for ov, seg in overlaps if ov > 0]
    if not overlapping:
        return ""
    return " ".join(seg.text.strip() for _, seg in sorted(overlapping, key=lambda pair: pair[1].start))


def main() -> int:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not installed -- apps/api/.venv/bin/pip install faster-whisper")
        return 1

    audio_path = Path(os.environ.get("AUDIO", str(DEFAULT_AUDIO)))
    ground_truth_path = Path(os.environ.get("GROUND_TRUTH", str(DEFAULT_GROUND_TRUTH)))
    if not audio_path.exists() or not ground_truth_path.exists():
        print(f"Missing fixture: {audio_path} or {ground_truth_path}")
        return 1

    model_size = os.environ.get("FASTER_WHISPER_MODEL", "small")
    device = os.environ.get("FASTER_WHISPER_DEVICE", "cuda")
    compute_type = os.environ.get("FASTER_WHISPER_COMPUTE_TYPE", "float16" if device == "cuda" else "int8")
    beam_size = int(os.environ.get("FASTER_WHISPER_BEAM_SIZE", "5"))

    ground_truth = _load_ground_truth(ground_truth_path)

    print(f"audio: {audio_path}")
    print(f"model={model_size} device={device} compute_type={compute_type} beam_size={beam_size}")

    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as exc:
        print(f"WhisperModel() construction failed: {type(exc).__name__}: {exc}")
        print("(if this is a CUDA error, try FASTER_WHISPER_DEVICE=cpu FASTER_WHISPER_COMPUTE_TYPE=int8)")
        return 1

    # Cold pass (model already loaded, but first inference pays kernel/
    # context warmup) discarded, matching every other script in this repo's
    # cold-then-warm convention.
    list(model.transcribe(str(audio_path), beam_size=beam_size, language="ko")[0])

    decode_start = time.perf_counter()
    segments_gen, info = model.transcribe(str(audio_path), beam_size=beam_size, language="ko")
    predicted_segments = list(segments_gen)  # must fully consume the generator before stopping the timer
    warm_decode_ms = (time.perf_counter() - decode_start) * 1000

    audio_duration = info.duration
    rtf = (warm_decode_ms / 1000) / audio_duration if audio_duration else float("nan")
    print(f"\nRTF: {rtf:.3f}x  (audio_duration={audio_duration:.2f}s, warm_decode_ms={warm_decode_ms:.1f})")
    print(f"segments returned: {len(predicted_segments)} (no diarization -- ASR only)")

    matched_by_id = {}
    print("\nPer-segment expected vs. predicted text:")
    for gt_seg in ground_truth:
        matched_text = _match_predicted_text(gt_seg, predicted_segments)
        matched_by_id[gt_seg["id"]] = matched_text
        print(f"  [{gt_seg['id']}]")
        print(f"    expected : {gt_seg['text']}")
        print(f"    predicted: {matched_text or '(no overlapping predicted segment)'}")

    print("\nClinical-anchor checks:")
    pass_count = 0
    for check in ACCURACY_CHECKS:
        text = _normalize(matched_by_id.get(check["segment_id"], ""))
        passed = any(_normalize(kw) in text for kw in check["keywords"])
        pass_count += passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {check['segment_id']}: {check['label']}")
    print(f"\n{pass_count}/{len(ACCURACY_CHECKS)} anchors passed")

    print(
        "\nNote: compare this pass count and the per-segment text directly against "
        "`make compare-asr-accuracy`'s sherpa-onnx output on the same file -- "
        "speed alone (see tasks/05_ASR_HARDWARE_SPEEDUP.md) must not decide the engine."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""`AUDIO=path/to/file.wav apps/api/.venv/bin/python scripts/diagnose_asr_stages.py`

tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1 diagnostic -- separate from
scripts/benchmark_audio.py (left untouched per explicit request). Runs the
local sherpa-onnx ASR pipeline once cold (to warm the provider's cached
models, same caching app/dependencies.py uses in the real app) then once
warm, and prints a per-turn breakdown of the warm run: diarization time,
and for each turn its clip duration, recognizer_auto decode time, whether
the ko-fallback recognizer fired, and its decode time if so -- plus
aggregates and RTF (real-time factor = inference time / audio duration).

Never prints decoded text, transcript, or audio content -- only counts and
durations ("진단 출력에는 녹음 내용이나 전사문을 넣지 마").

Same cost/scope rules as scripts/benchmark_audio.py: opt-in only, never
part of `make test`/`make e2e`. Free -- local ASR only, no OpenAI call.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))


def _load_env_local() -> None:
    env_path = REPO_ROOT / "apps" / "api" / ".env.local"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _print_turns_table(turns: list[dict]) -> None:
    header = f"{'turn':>5}{'duration_s':>12}{'auto_ms':>10}{'ko_fired':>10}{'ko_ms':>10}"
    print(header)
    print("-" * len(header))
    for t in turns:
        ko_ms = f"{t['ko_decode_ms']:.1f}" if t["ko_decode_ms"] is not None else "-"
        print(
            f"{t['index']:>5}{t['duration_seconds']:>12.3f}{t['auto_decode_ms']:>10.1f}"
            f"{str(t['ko_fallback']):>10}{ko_ms:>10}"
        )


def main() -> int:
    audio_path = os.environ.get("AUDIO")
    if not audio_path:
        print("Usage: AUDIO=path/to/file.wav python3 scripts/diagnose_asr_stages.py")
        return 1
    if not Path(audio_path).exists():
        print(f"File not found: {audio_path}")
        return 1

    _load_env_local()

    from app.domain.errors import AriadError
    from app.domain.models import AudioAsset
    from app.providers.sherpa_onnx_asr import SherpaOnnxASRProvider, models_available

    models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
    if not models_available(models_dir):
        print(f"sherpa-onnx model files not found under {models_dir!r}. See README.md.")
        return 1

    fake_asset = AudioAsset(
        id="diagnostic",
        encounter_id="diagnostic",
        kind="original",
        size_bytes=Path(audio_path).stat().st_size,
        duration_seconds=0.0,  # not used by the provider itself
        created_at="1970-01-01T00:00:00+00:00",
    )

    # One provider instance for both runs, exactly like the process-lifetime
    # cache app.dependencies hands out in the real app -- run 1 pays the
    # model-load cost, run 2 is the "warm" one this diagnostic reports on.
    provider = SherpaOnnxASRProvider(models_dir=models_dir)

    print(f"[1/2] Cold run (warms the model cache) on {audio_path} ...")
    try:
        provider.transcribe(fake_asset, audio_path)
    except AriadError as exc:
        print(f"Cold run failed: [{exc.code}] {exc.message}")
        return 1

    print("[2/2] Warm run, capturing per-turn diagnostics ...")
    diagnostics: dict = {}
    try:
        segments = provider.transcribe(fake_asset, audio_path, diagnostics=diagnostics)
    except AriadError as exc:
        print(f"Warm run failed: [{exc.code}] {exc.message}")
        return 1

    audio_duration = diagnostics.get("audio_duration_seconds", 0.0)
    inference_ms = (
        diagnostics.get("diarize_ms", 0.0)
        + diagnostics.get("auto_total_ms", 0.0)
        + diagnostics.get("ko_total_ms", 0.0)
    )
    rtf = (inference_ms / 1000) / audio_duration if audio_duration else float("nan")

    print(f"\naudio_duration_seconds: {audio_duration:.2f}")
    print(f"diarize_ms: {diagnostics.get('diarize_ms', 0.0):.1f}")
    print(
        f"auto:       {diagnostics.get('auto_call_count', 0)} call(s), "
        f"{diagnostics.get('auto_total_ms', 0.0):.1f}ms total, "
        f"{diagnostics.get('auto_total_input_seconds', 0.0):.2f}s input audio"
    )
    print(
        f"ko_fallback: {diagnostics.get('ko_call_count', 0)} call(s), "
        f"{diagnostics.get('ko_total_ms', 0.0):.1f}ms total, "
        f"{diagnostics.get('ko_total_input_seconds', 0.0):.2f}s input audio"
    )
    print(f"inference_ms (diarize+auto+ko): {inference_ms:.1f}")
    print(f"RTF (inference / audio duration): {rtf:.2f}x")
    print(f"segments returned: {len(segments)}")

    print("\nPer-turn breakdown (warm run):\n")
    _print_turns_table(diagnostics.get("turns", []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

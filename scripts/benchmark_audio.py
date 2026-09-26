#!/usr/bin/env python3
"""`make benchmark-audio AUDIO=path/to/file.wav [RUNS=3]`

Live latency benchmark against REAL providers -- same cost/scope rules as
scripts/test_provider_audio.py (tasks/02_AUDIO_PIPELINE.md section 12: never
part of `make test`/`make e2e`).

Runs the local sherpa-onnx ASR pipeline once "cold" (fresh provider, models
not yet loaded) then RUNS times "warm" (same provider instance, reusing the
already-loaded models -- this is exactly the caching
tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1 added in app/dependencies.py /
app/providers/sherpa_onnx_asr.py, verified here with real wall-clock numbers
instead of just the unit-level call-count regression test).

If OPENAI_API_KEY is set, optionally continues into structure_llm/
explanation_llm (paid, asks for confirmation) using the same naive
speaker->role labeling scripts/test_provider_audio.py uses -- a one-shot CLI
benchmark, not the real role-confirmation UI.

Prints only stage names, durations, and counts -- never audio/transcript/
explanation content (tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1: "실제
patient content를 출력하지 않는다").
"""

from __future__ import annotations

import os
import statistics
import sys
from collections import defaultdict
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


def _print_table(records_by_run: list[list], *, cold_index: int = 0) -> None:
    """records_by_run[i] is run i's list[StageRecord]. Prints cold (run
    cold_index) alongside warm median/min/max, per stage."""
    warm_runs = [r for i, r in enumerate(records_by_run) if i != cold_index]
    by_stage_warm: dict[str, list[float]] = defaultdict(list)
    for run in warm_runs:
        for rec in run:
            by_stage_warm[rec.stage].append(rec.duration_ms)
    cold_by_stage = {rec.stage: rec.duration_ms for rec in records_by_run[cold_index]}

    stages = sorted(set(cold_by_stage) | set(by_stage_warm))
    header = f"{'stage':<20}{'cold_ms':>12}{'warm_median_ms':>16}{'warm_min_ms':>14}{'warm_max_ms':>14}"
    print(header)
    print("-" * len(header))
    for stage in stages:
        cold = cold_by_stage.get(stage)
        warm = by_stage_warm.get(stage, [])
        cold_s = f"{cold:.1f}" if cold is not None else "-"
        median_s = f"{statistics.median(warm):.1f}" if warm else "-"
        min_s = f"{min(warm):.1f}" if warm else "-"
        max_s = f"{max(warm):.1f}" if warm else "-"
        print(f"{stage:<20}{cold_s:>12}{median_s:>16}{min_s:>14}{max_s:>14}")


def main() -> int:
    audio_path = os.environ.get("AUDIO")
    if not audio_path:
        print("Usage: make benchmark-audio AUDIO=path/to/file.wav [RUNS=3]")
        return 1
    if not Path(audio_path).exists():
        print(f"File not found: {audio_path}")
        return 1
    runs = int(os.environ.get("RUNS", "3"))

    _load_env_local()

    from app.domain.errors import AriadError
    from app.domain.models import AudioAsset
    from app.observability import StageTimer
    from app.providers.sherpa_onnx_asr import SherpaOnnxASRProvider, models_available

    models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
    if not models_available(models_dir):
        print(f"sherpa-onnx model files not found under {models_dir!r}. See README.md.")
        return 1

    fake_asset = AudioAsset(
        id="benchmark",
        encounter_id="benchmark",
        kind="original",
        size_bytes=Path(audio_path).stat().st_size,
        duration_seconds=0.0,  # not used by the provider itself
        created_at="1970-01-01T00:00:00+00:00",
    )

    # One provider instance for the whole run, exactly like the cached
    # instance app.dependencies now hands out in the real app -- the point
    # of "cold vs warm" here is to prove that caching actually helps.
    provider = SherpaOnnxASRProvider(models_dir=models_dir)
    total_runs = 1 + runs
    print(f"[1/2] Running ASR {total_runs} times on {audio_path} (1 cold + {runs} warm) ...")
    all_records = []
    segments = None
    for i in range(total_runs):
        timer = StageTimer()
        try:
            segments = provider.transcribe(fake_asset, audio_path, stage_timer=timer)
        except AriadError as exc:
            print(f"  run {i} failed: [{exc.code}] {exc.message}")
            return 1
        label = "cold" if i == 0 else f"warm[{i}]"
        print(f"  run {i} ({label}): {sum(r.duration_ms for r in timer.records):.1f}ms total, {len(segments)} segment(s)")
        all_records.append(timer.records)

    print("\nASR stage latency:\n")
    _print_table(all_records)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("\n[2/2] OPENAI_API_KEY not set -- skipping the (paid) LLM stage benchmark.")
        return 0

    print("\n[2/2] OPENAI_API_KEY is set -- benchmarking structure_llm/explanation_llm now (paid).")
    confirm = input("Continue? [y/N] ").strip().lower()
    if confirm != "y":
        print("Skipped.")
        return 0

    from app.pipeline.explanation import generate_patient_explanation
    from app.pipeline.structure import structure_encounter
    from app.providers.openai_llm import OpenAILLMProvider

    role_by_speaker = {seg.speaker: "화자" for seg in segments}
    transcript_text = "\n".join(f"{role_by_speaker[s.speaker]}: {s.text}" for s in segments)

    model = os.environ.get("OPENAI_TEXT_MODEL") or "gpt-4o-mini"
    llm_provider = OpenAILLMProvider(api_key=api_key, model=model)

    llm_records = []
    for i in range(total_runs):
        timer = StageTimer()
        try:
            structure = structure_encounter(transcript_text, llm_provider, timer)
            generate_patient_explanation(structure, llm_provider, timer)
        except AriadError as exc:
            print(f"  LLM run {i} failed: [{exc.code}] {exc.message}")
            return 1
        label = "cold" if i == 0 else f"warm[{i}]"
        print(f"  run {i} ({label}): {sum(r.duration_ms for r in timer.records):.1f}ms total")
        llm_records.append(timer.records)

    print("\nLLM stage latency:\n")
    _print_table(llm_records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

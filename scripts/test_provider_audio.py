#!/usr/bin/env python3
"""`make test-provider-audio AUDIO=path/to/file.wav`

Live smoke test against REAL providers -- never run as part of `make test`
or `make e2e` (tasks/02_AUDIO_PIPELINE.md section 12: "기본 make test나
make e2e는 비용이 발생하는 실제 API를 호출하면 안 된다").

1. Runs the local sherpa-onnx ASR pipeline on the given audio file (free,
   local compute -- requires ARIAD_SHERPA_MODELS_DIR to have the model
   files; see README.md).
2. If OPENAI_API_KEY is set, also runs the OpenAI text LLM stage
   (structure_transcript -> patient_explanation) on the resulting
   transcript. This step calls the real OpenAI API and incurs real cost --
   it only runs when a key is present, and this script prints a warning
   before doing so.

Reads apps/api/.env.local if present (never committed -- see .gitignore)
so you don't have to export the key into your shell manually.
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


def main() -> int:
    audio_path = os.environ.get("AUDIO")
    if not audio_path:
        print("Usage: make test-provider-audio AUDIO=path/to/file.wav")
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
        print(f"sherpa-onnx model files not found under {models_dir!r}.")
        print("Download them (see README.md) and set ARIAD_SHERPA_MODELS_DIR, then retry.")
        return 1

    print(f"[1/2] Running local sherpa-onnx ASR on {audio_path} ...")
    fake_asset = AudioAsset(
        id="smoke-test",
        encounter_id="smoke-test",
        kind="original",
        size_bytes=Path(audio_path).stat().st_size,
        duration_seconds=0.0,  # not used by the provider itself
        created_at="1970-01-01T00:00:00+00:00",
    )

    try:
        segments = SherpaOnnxASRProvider(models_dir=models_dir).transcribe(fake_asset, audio_path)
    except AriadError as exc:
        print(f"ASR failed: [{exc.code}] {exc.message}")
        return 1

    print(f"  {len(segments)} segment(s):")
    for seg in segments:
        print(f"    [{seg.start:6.2f}-{seg.end:6.2f}] {seg.speaker}: {seg.text}")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("\n[2/2] OPENAI_API_KEY not set -- skipping the (paid) text LLM step.")
        return 0

    print("\n[2/2] OPENAI_API_KEY is set -- calling the real OpenAI API now (this costs money).")
    confirm = input("Continue? [y/N] ").strip().lower()
    if confirm != "y":
        print("Skipped.")
        return 0

    from app.pipeline.explanation import generate_patient_explanation
    from app.pipeline.structure import structure_encounter
    from app.providers.openai_llm import OpenAILLMProvider

    # Naive speaker->role labeling for a one-shot smoke test -- the real
    # app always requires a human PATCH /speaker-roles confirmation first.
    role_by_speaker = {seg.speaker: "화자" for seg in segments}
    transcript_text = "\n".join(f"{role_by_speaker[s.speaker]}: {s.text}" for s in segments)

    model = os.environ.get("OPENAI_TEXT_MODEL") or "gpt-4o-mini"
    provider = OpenAILLMProvider(api_key=api_key, model=model)
    try:
        structure = structure_encounter(transcript_text, provider)
        explanation = generate_patient_explanation(structure, provider)
    except AriadError as exc:
        print(f"LLM step failed: [{exc.code}] {exc.message}")
        return 1

    print("\nStructure:")
    print(structure.model_dump_json(indent=2, exclude_none=True))
    print("\nExplanation:")
    print(explanation.model_dump_json(indent=2, exclude_none=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

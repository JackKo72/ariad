#!/usr/bin/env python3
"""`AUDIO=data/annotations/icu.m4a NUM_SPEAKERS=2 make draft-annotation`

tasks/08_REAL_VOICE_REFERENCE_ANNOTATION.md step 1: turns a simulated
(role-played, no real patient) recording into an Audacity label-track DRAFT
for a clinician to correct, instead of annotating from scratch.

Output: <OUT_DIR>/<stem>.draft.txt -- Audacity "Import Labels" format, one
region per line: `start<TAB>end<TAB>label`, label = `SPEAKER|TYPE|text`:
  SPEAKER  draft cluster (A, B, ...) -> replace with DOC, DOC2, PT, GUARD,
           STAFF, BG1, BG2 ... (see scripts/labels_to_reference.py)
  TYPE     `?` -> replace with exam / order / explain / other
  text     the app's own ASR output when Whisper models are present (fix
           only medical terms and numbers), empty otherwise
Then `make labels-to-reference LABELS=...` turns the corrected file into a
reference for `make eval-diarization-der`.

Env: AUDIO (required), NUM_SPEAKERS (default 0 = auto; set the known
head-count for a cleaner draft), TEXT (default auto: 1 if Whisper models
exist), OUT_DIR (default data/annotations -- gitignored, never commit).
Prints counts only, never the decoded text.
"""

from __future__ import annotations

import os
import sys
import tempfile
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))


def diarization_only(audio_path: Path, models_dir: str, num_speakers: int) -> list[tuple[float, float, str, str]]:
    import numpy as np

    from app.audio.preprocess import standardize_audio
    from app.providers.sherpa_onnx_asr import _speaker_label, build_diarizer

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "16k.wav"
        standardize_audio(audio_path, wav_path, "none")
        with wave.open(str(wav_path)) as w:
            frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    turns = build_diarizer(models_dir, "cpu", num_speakers).process(frames).sort_by_start_time()
    return [(t.start, t.end, _speaker_label(t.speaker), "") for t in turns]


def with_text(audio_path: Path, models_dir: str, num_speakers: int) -> list[tuple[float, float, str, str]]:
    from app.domain.models import AudioAsset
    from app.providers.sherpa_onnx_asr import SherpaOnnxASRProvider

    asset = AudioAsset(
        id="draft-annotation", encounter_id="draft-annotation", kind="original",
        size_bytes=audio_path.stat().st_size, duration_seconds=0.0, created_at="1970-01-01T00:00:00+00:00",
    )
    provider = SherpaOnnxASRProvider(models_dir=models_dir, num_speakers=num_speakers)
    segments = provider.transcribe(asset, str(audio_path))
    return [(s.start, s.end, s.speaker, s.text) for s in segments]


def to_label_lines(turns: list[tuple[float, float, str, str]]) -> list[str]:
    # Audacity splits label lines on tabs; keep the text on one line.
    return [f"{start:.3f}\t{end:.3f}\t{speaker}|?|{' '.join(text.split())}" for start, end, speaker, text in turns]


def main() -> int:
    from app.providers.sherpa_onnx_asr import models_available

    audio = os.environ.get("AUDIO")
    if not audio or not Path(audio).exists():
        print("Usage: AUDIO=path/to/recording [NUM_SPEAKERS=2] python3 scripts/draft_reference_annotation.py")
        return 1
    audio_path = Path(audio)
    models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
    num_speakers = int(os.environ.get("NUM_SPEAKERS", "0"))
    out_dir = Path(os.environ.get("OUT_DIR", REPO_ROOT / "data" / "annotations"))

    text_env = os.environ.get("TEXT")
    use_text = models_available(models_dir) if text_env is None else text_env == "1"
    if use_text and not models_available(models_dir):
        print(f"TEXT=1 but Whisper/diarization models not found under {models_dir!r} (README.md).")
        return 1

    turns = (with_text if use_text else diarization_only)(audio_path, models_dir, num_speakers)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{audio_path.stem}.draft.txt"
    out_path.write_text("\n".join(to_label_lines(turns)) + "\n", encoding="utf-8")

    speakers = sorted({speaker for _s, _e, speaker, _t in turns})
    print(f"{len(turns)} regions, draft speakers {speakers}, text={'ASR' if use_text else 'empty'} -> {out_path}")
    print("Audacity: File > Import > Audio, then File > Import > Labels; fix SPEAKER|TYPE|text; "
          "File > Export > Export Labels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

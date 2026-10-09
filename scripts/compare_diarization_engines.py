#!/usr/bin/env python3
"""`AUDIO=path/to/file.wav apps/api/.venv/bin/python scripts/compare_diarization_engines.py`

tasks/05_ASR_HARDWARE_SPEEDUP.md Path C: after Path A (ASR on GPU) and Path B
(ASR+diarization in separate processes -- measured 1.44x real speedup) were
both validated on the user's real hardware, diarization itself (sherpa-onnx,
RTF ~0.17) is now the sole remaining bottleneck short of the 10-min-in-60s
goal -- and sherpa-onnx's current Python API has no CUDA provider hook on
its segmentation step; forcing provider="cuda" there was already measured to
make diarization *slower*, not faster (see tasks/05's real-hardware section).

This compares that CPU baseline against pyannote.audio -- the original
PyTorch implementation sherpa-onnx's own C++ diarization was ported from --
which may get genuine CUDA acceleration where the ported version cannot.
That is a hypothesis drawn from pyannote.audio's public documentation, not a
measurement -- this sandbox has no GPU and neither package installed, so
this script exists to let the measurement happen on real hardware instead
of guessing at a number.

Hard requirements this script checks and reports rather than assumes:
  - pyannote.audio must be installed (`pip install pyannote.audio`) -- a
    separate package from sherpa-onnx, pulls in torch.
  - pyannote/speaker-diarization-3.1 (and the segmentation model it depends
    on) are GATED on HuggingFace Hub: the account behind the access token
    must accept both models' usage conditions on huggingface.co first, or
    Pipeline.from_pretrained() fails with a 401/permission error -- this
    script surfaces that real error message rather than a generic "failed".
  - HUGGINGFACE_TOKEN (or HF_TOKEN) env var must be set to that account's
    access token.
  - For the cuda candidate, torch itself must report a CUDA device
    (torch.cuda.is_available()) -- a CPU-only torch wheel is a different
    failure from "no GPU present" and this script does not conflate them.

Same measurement discipline as scripts/compare_asr_engines.py (reuses its
UtilizationSampler): separate cold load from a warm diarize call, sample
GPU/CPU utilization *during* the warm call rather than trusting that
construction/`.to(cuda)` merely succeeded, and never substitute a public
benchmark number for this machine's own result. Never prints speaker labels
or any transcript content -- only turn counts, timestamps, and durations.
Opt-in, free (no OpenAI call), never part of `make test`/`make e2e`. Real
recordings and their outputs must not be committed to this repository.
"""

from __future__ import annotations

import json
import os
import sys
import time
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


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


def _load_pcm(audio_path: Path) -> tuple[object, int, float]:
    import tempfile

    import numpy as np

    from app.audio.preprocess import standardize_audio

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "16k.wav"
        standardize_audio(audio_path, wav_path, "none")
        with wave.open(str(wav_path)) as w:
            sample_rate = w.getframerate()
            frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return frames, sample_rate, len(frames) / sample_rate


def _run_sherpa(audio_path: Path, provider: str) -> dict:
    from app.providers.sherpa_onnx_asr import build_diarizer, models_available
    from compare_asr_engines import UtilizationSampler

    models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
    if not models_available(models_dir):
        return {"skipped": True, "reason": f"sherpa-onnx model files not found under {models_dir!r}"}

    frames, _sample_rate, audio_duration = _load_pcm(audio_path)

    try:
        load_start = time.perf_counter()
        diarizer = build_diarizer(models_dir, provider)
        load_ms = (time.perf_counter() - load_start) * 1000
    except Exception as exc:
        return {"skipped": True, "reason": f"build_diarizer() failed: {type(exc).__name__}: {exc}"}

    diarizer.process(frames)  # cold warm-up, discarded

    with UtilizationSampler() as sampler:
        decode_start = time.perf_counter()
        turns = diarizer.process(frames).sort_by_start_time()
        warm_ms = (time.perf_counter() - decode_start) * 1000

    return {
        "skipped": False,
        "cold_load_ms": round(load_ms, 1),
        "warm_diarize_ms": round(warm_ms, 1),
        "audio_duration_seconds": round(audio_duration, 2),
        "rtf": round(warm_ms / 1000 / audio_duration, 3) if audio_duration else None,
        "turns_detected": len(turns),
        "speakers_detected": len({t.speaker for t in turns}),
        "segments": [(t.start, t.end, str(t.speaker)) for t in turns],
        **sampler.summary(),
    }


def _run_pyannote(audio_path: Path, device: str) -> dict:
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as exc:
        return {
            "skipped": True,
            "reason": (
                f"pyannote.audio(또는 torch) 미설치: {exc}. "
                "apps/api/.venv/bin/pip install pyannote.audio 로 설치(torch가 함께 설치됨)."
            ),
        }

    if device == "cuda" and not torch.cuda.is_available():
        return {
            "skipped": True,
            "reason": (
                "torch.cuda.is_available() == False -- GPU가 없거나 CPU-only torch wheel이 설치된 "
                "것으로 보임. sherpa-onnx의 CUDA 미지원과는 별개의 원인이므로 혼동하지 말 것 "
                "(필요하다면 pip install torch --index-url https://download.pytorch.org/whl/cu121 등 "
                "CUDA 지원 torch로 재설치)."
            ),
        }

    token = os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN")
    if not token:
        return {
            "skipped": True,
            "reason": (
                "HUGGINGFACE_TOKEN(또는 HF_TOKEN) 환경변수가 없음. pyannote/speaker-diarization-3.1은 "
                "HuggingFace Hub에서 접근 제한(gated)된 모델이다 -- huggingface.co에 로그인한 뒤 "
                "pyannote/speaker-diarization-3.1과 pyannote/segmentation-3.0 각각의 라이선스에 "
                "동의하고, Settings > Access Tokens에서 토큰을 발급해 설정해야 한다."
            ),
        }

    try:
        load_start = time.perf_counter()
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
        pipeline.to(torch.device(device))
        load_ms = (time.perf_counter() - load_start) * 1000
    except Exception as exc:
        # Real error surfaced verbatim (never audio/transcript content) --
        # a 401/403 here almost always means the gated models' license
        # wasn't accepted yet on the token's HF account, not a code bug.
        return {"skipped": True, "reason": f"Pipeline.from_pretrained()/to() failed: {type(exc).__name__}: {exc}"}

    from app.audio.validation import probe_audio
    from compare_asr_engines import UtilizationSampler

    pipeline(str(audio_path))  # cold warm-up, discarded

    with UtilizationSampler() as sampler:
        decode_start = time.perf_counter()
        diarization = pipeline(str(audio_path))
        warm_ms = (time.perf_counter() - decode_start) * 1000

    audio_duration = probe_audio(str(audio_path)).duration_seconds
    turns = list(diarization.itertracks(yield_label=True))

    return {
        "skipped": False,
        "cold_load_ms": round(load_ms, 1),
        "warm_diarize_ms": round(warm_ms, 1),
        "audio_duration_seconds": round(audio_duration, 2),
        "rtf": round(warm_ms / 1000 / audio_duration, 3) if audio_duration else None,
        "turns_detected": len(turns),
        "speakers_detected": len({label for _seg, _track, label in turns}),
        "segments": [(seg.start, seg.end, str(label)) for seg, _track, label in turns],
        "device": device,
        **sampler.summary(),
    }


# Sortformer streaming presets from the nvidia/diar_streaming_sortformer_4spk-v2
# model card (units: 80 ms frames). "high" = ~10 s latency, enough for
# "finished right after the encounter ends" without ultra-low-latency cost.
_SORTFORMER_PRESETS = {
    "high": {"chunk_len": 124, "chunk_right_context": 1, "fifo_len": 124,
             "spkcache_update_period": 124, "spkcache_len": 188},
    "low": {"chunk_len": 6, "chunk_right_context": 7, "fifo_len": 188,
            "spkcache_update_period": 144, "spkcache_len": 188},
}


def _run_sortformer(audio_path: Path, device: str, preset: str) -> dict:
    """NeMo Sortformer (end-to-end, max 4 speakers). Uses the streaming v2
    model -- v1 is CC-BY-NC (non-commercial), v2 is CC-BY-4.0. Trained mainly
    on English; Korean clinical performance is unmeasured, which is exactly
    what this candidate exists to measure."""
    try:
        import torch
        from nemo.collections.asr.models import SortformerEncLabelModel
    except ImportError as exc:
        return {
            "skipped": True,
            "reason": (
                f"nemo_toolkit[asr](또는 torch) 미설치: {exc}. "
                "pip install Cython packaging && "
                "pip install 'nemo_toolkit[asr]' 로 설치 (libsndfile1, ffmpeg 필요)."
            ),
        }

    if device == "cuda" and not torch.cuda.is_available():
        return {"skipped": True, "reason": "torch.cuda.is_available() == False -- GPU 없음 또는 CPU-only torch."}

    import tempfile

    from app.audio.preprocess import standardize_audio
    from app.audio.validation import probe_audio
    from compare_asr_engines import UtilizationSampler

    try:
        load_start = time.perf_counter()
        model = SortformerEncLabelModel.from_pretrained(
            "nvidia/diar_streaming_sortformer_4spk-v2", map_location=device
        )
        model.eval()
        for name, value in _SORTFORMER_PRESETS[preset].items():
            setattr(model.sortformer_modules, name, value)
        model.sortformer_modules._check_streaming_parameters()
        load_ms = (time.perf_counter() - load_start) * 1000
    except Exception as exc:
        return {"skipped": True, "reason": f"from_pretrained() failed: {type(exc).__name__}: {exc}"}

    with tempfile.TemporaryDirectory() as tmp:
        # Sortformer requires mono/16 kHz -- same standardization the app uses.
        wav_path = Path(tmp) / "16k.wav"
        standardize_audio(audio_path, wav_path, "none")

        model.diarize(audio=[str(wav_path)], batch_size=1)  # cold warm-up, discarded

        with UtilizationSampler() as sampler:
            decode_start = time.perf_counter()
            segments = model.diarize(audio=[str(wav_path)], batch_size=1)[0]
            warm_ms = (time.perf_counter() - decode_start) * 1000

    # Each segment is "begin end speaker_N" (string) in current NeMo; accept a
    # (begin, end, label) sequence too, and never print the label.
    parsed = [tuple(s.split()) if isinstance(s, str) else tuple(s) for s in segments]
    turns = [(float(begin), float(end), str(label)) for begin, end, label in parsed]
    labels = {label for _begin, _end, label in turns}
    audio_duration = probe_audio(str(audio_path)).duration_seconds

    return {
        "skipped": False,
        "cold_load_ms": round(load_ms, 1),
        "warm_diarize_ms": round(warm_ms, 1),
        "audio_duration_seconds": round(audio_duration, 2),
        "rtf": round(warm_ms / 1000 / audio_duration, 3) if audio_duration else None,
        "turns_detected": len(segments),
        "speakers_detected": len(labels),
        "segments": turns,
        "device": device,
        "preset": preset,
        **sampler.summary(),
    }


CANDIDATES = {
    "sherpa_cpu": lambda audio: _run_sherpa(audio, provider="cpu"),
    "sherpa_cuda": lambda audio: _run_sherpa(audio, provider="cuda"),
    "pyannote_cpu": lambda audio: _run_pyannote(audio, device="cpu"),
    "pyannote_cuda": lambda audio: _run_pyannote(audio, device="cuda"),
    "sortformer_cuda": lambda audio: _run_sortformer(audio, device="cuda", preset="high"),
    "sortformer_cuda_low": lambda audio: _run_sortformer(audio, device="cuda", preset="low"),
}


def main() -> int:
    audio_path_str = os.environ.get("AUDIO")
    if not audio_path_str:
        print("Usage: AUDIO=path/to/file.wav python3 scripts/compare_diarization_engines.py [ENGINES=a,b,c]")
        print(f"Available engine keys: {', '.join(CANDIDATES)}")
        return 1
    audio_path = Path(audio_path_str)
    if not audio_path.exists():
        print(f"File not found: {audio_path}")
        return 1

    _load_env_local()

    requested = os.environ.get("ENGINES")
    engine_keys = [k.strip() for k in requested.split(",")] if requested else list(CANDIDATES)

    print(f"audio: {audio_path}")
    print(f"engines: {engine_keys}\n")

    results = {}
    for key in engine_keys:
        if key not in CANDIDATES:
            print(f"[{key}] unknown engine key, skipping")
            continue
        print(f"[{key}] running ...")
        result = CANDIDATES[key](audio_path)
        results[key] = result
        if result.get("skipped"):
            print(f"  SKIPPED: {result['reason']}")
        else:
            # "segments" (per-turn timestamps + labels) feeds
            # scripts/eval_diarization_der.py only -- kept out of this output.
            printable = {k: v for k, v in result.items() if k != "segments"}
            print(json.dumps(printable, ensure_ascii=False, indent=2))
        print()

    print("=" * 78)
    print("요약 (RTF = warm_diarize_ms / audio_duration_ms; 낮을수록 빠름, 목표 <= 0.1)")
    print("=" * 78)
    header = f"{'engine':<20}{'RTF':>8}{'warm_ms':>12}{'gpu_util%':>12}{'cpu_util%':>12}{'speakers':>10}"
    print(header)
    print("-" * len(header))
    for key, result in results.items():
        if result.get("skipped"):
            print(f"{key:<20}{'SKIPPED':>8}")
            continue
        rtf = result.get("rtf")
        warm_ms = result.get("warm_diarize_ms")
        gpu_util = result.get("gpu_util_avg_pct")
        cpu_util = result.get("cpu_util_avg_pct")
        speakers = result.get("speakers_detected")
        print(
            f"{key:<20}"
            f"{(f'{rtf:.3f}' if rtf is not None else '-'):>8}"
            f"{(f'{warm_ms:.0f}' if warm_ms is not None else '-'):>12}"
            f"{(f'{gpu_util:.0f}' if gpu_util is not None else '-'):>12}"
            f"{(f'{cpu_util:.0f}' if cpu_util is not None else '-'):>12}"
            f"{(str(speakers) if speakers is not None else '-'):>10}"
        )
    print(
        "\n주의: pyannote_cuda의 gpu_util%가 0에 가깝거나 '-'이면 torch가 모델을 cuda 디바이스로 "
        "옮기는 데는 성공했어도 실제 연산이 GPU에서 돌지 않았을 수 있다 -- "
        "'pipeline.to(cuda) 성공'과 '실제 가속'을 혼동하지 말 것(sherpa-onnx provider=cuda가 "
        "fallback했던 것과 같은 함정)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

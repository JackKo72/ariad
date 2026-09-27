#!/usr/bin/env python3
"""`AUDIO=path/to/file.wav apps/api/.venv/bin/python scripts/compare_asr_engines.py`

tasks/05_ASR_HARDWARE_SPEEDUP.md items 2-4: fair, same-machine comparison of
independent ASR engine/provider candidates against the current default
(sherpa-onnx Whisper large-v3, CPU, ko_only), so the user can pick a
direction with real numbers from their own hardware -- never from a public
benchmark substituted for this machine's result.

For each candidate this measures, separately:
  - model_load_ms: cold construction (once, discarded from the "warm" number)
  - warm_decode_ms: a second, warm decode -- the number that matters for
    "user waits after recording ends"
  - wall_ms: model_load_ms + warm_decode_ms (total first-run cost)
  - RTF = warm_decode_ms / (audio_duration_seconds * 1000)
  - CPU/GPU utilization sampled by a background thread *during* warm decode
    (not just "GPU capability detected") -- avg/peak CPU%, avg/peak GPU%,
    peak GPU VRAM MB. If nvidia-smi isn't present, GPU fields are None and
    say so -- never a fabricated number.
faster-whisper's segments generator is fully consumed (list()) before
stopping the decode timer, per tasks/05 item 4's explicit requirement.

Candidates run only if their models/packages are actually available;
missing ones are skipped with a clear reason and installation/download
pointer, never silently omitted from the printed table. Nothing here
changes ARIAD's default ASR path -- this is a standalone comparison tool.

Never prints decoded text or any audio/transcript content -- only counts,
durations, and utilization numbers. Opt-in, never part of `make
test`/`make e2e`. Real audio files and their outputs must not be committed
to this repository.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Optional

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


class UtilizationSampler:
    """Background thread polling GPU (nvidia-smi) and CPU (/proc/stat)
    utilization every 0.3s while a candidate's decode runs. Reports
    avg/peak, not just "a GPU exists" -- tasks/05 item 1: "GPU 사용 가능하다는
    표시만으로 충분하다고 판단하지 마"."""

    def __init__(self, interval_seconds: float = 0.3):
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.gpu_samples: list[tuple[float, float]] = []  # (util%, vram_mb)
        self.cpu_samples: list[float] = []
        self._has_nvidia_smi = self._check_nvidia_smi()

    @staticmethod
    def _check_nvidia_smi() -> bool:
        try:
            subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=5, check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _read_cpu_total_busy() -> tuple[int, int]:
        line = Path("/proc/stat").read_text().splitlines()[0]
        fields = [int(x) for x in line.split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields)
        return total, idle

    def _sample_gpu(self) -> Optional[tuple[float, float]]:
        if not self._has_nvidia_smi:
            return None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            first_line = result.stdout.strip().splitlines()[0]
            util_str, mem_str = [p.strip() for p in first_line.split(",")]
            return float(util_str), float(mem_str)
        except Exception:
            return None

    def _loop(self) -> None:
        prev_total, prev_idle = self._read_cpu_total_busy()
        while not self._stop.is_set():
            time.sleep(self._interval)
            total, idle = self._read_cpu_total_busy()
            d_total, d_idle = total - prev_total, idle - prev_idle
            if d_total > 0:
                self.cpu_samples.append(100.0 * (1 - d_idle / d_total))
            prev_total, prev_idle = total, idle
            gpu = self._sample_gpu()
            if gpu is not None:
                self.gpu_samples.append(gpu)

    def __enter__(self) -> "UtilizationSampler":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def summary(self) -> dict:
        out = {
            "cpu_util_avg_pct": round(sum(self.cpu_samples) / len(self.cpu_samples), 1) if self.cpu_samples else None,
            "cpu_util_peak_pct": round(max(self.cpu_samples), 1) if self.cpu_samples else None,
        }
        if not self._has_nvidia_smi:
            out["gpu_util_avg_pct"] = None
            out["gpu_util_peak_pct"] = None
            out["gpu_vram_peak_mb"] = None
            out["gpu_note"] = "nvidia-smi not found -- no NVIDIA GPU, or driver not on PATH"
        elif not self.gpu_samples:
            out["gpu_util_avg_pct"] = None
            out["gpu_util_peak_pct"] = None
            out["gpu_vram_peak_mb"] = None
            out["gpu_note"] = "nvidia-smi present but returned no samples during the run"
        else:
            utils = [s[0] for s in self.gpu_samples]
            vrams = [s[1] for s in self.gpu_samples]
            out["gpu_util_avg_pct"] = round(sum(utils) / len(utils), 1)
            out["gpu_util_peak_pct"] = round(max(utils), 1)
            out["gpu_vram_peak_mb"] = round(max(vrams), 1)
        return out


def _read_wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def _run_sherpa_whisper(audio_path: Path, provider: str, ko_mode: str) -> dict:
    from app.domain.errors import AriadError
    from app.domain.models import AudioAsset
    from app.providers.sherpa_onnx_asr import SherpaOnnxASRProvider, models_available

    models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
    if not models_available(models_dir):
        return {"skipped": True, "reason": f"whisper large-v3 model files not found under {models_dir!r}"}

    fake_asset = AudioAsset(
        id="compare", encounter_id="compare", kind="original",
        size_bytes=audio_path.stat().st_size, duration_seconds=0.0,
        created_at="1970-01-01T00:00:00+00:00",
    )
    try:
        instance = SherpaOnnxASRProvider(models_dir=models_dir, provider=provider, ko_mode=ko_mode)
    except ValueError as exc:
        return {"skipped": True, "reason": str(exc)}

    load_start = time.perf_counter()
    try:
        instance.transcribe(fake_asset, str(audio_path))
    except AriadError as exc:
        return {"skipped": True, "reason": f"cold run failed: [{exc.code}] {exc.message}"}
    model_load_ms = (time.perf_counter() - load_start) * 1000  # includes one decode pass too; see note below

    diagnostics: dict = {}
    with UtilizationSampler() as sampler:
        decode_start = time.perf_counter()
        try:
            segments = instance.transcribe(fake_asset, str(audio_path), diagnostics=diagnostics)
        except AriadError as exc:
            return {"skipped": True, "reason": f"warm run failed: [{exc.code}] {exc.message}"}
        warm_decode_ms = (time.perf_counter() - decode_start) * 1000

    audio_duration = diagnostics.get("audio_duration_seconds") or _read_wav_duration_seconds(audio_path)
    return {
        "skipped": False,
        # model_load_ms here is "cold run total" (load + one decode), since
        # SherpaOnnxASRProvider doesn't expose model loading standalone --
        # scripts/diagnose_asr_stages.py's asr_model_load stage (via
        # StageTimer) is the precise version of this number; this script's
        # own point is the engine-to-engine comparison via warm_decode_ms.
        "cold_run_total_ms": round(model_load_ms, 1),
        "warm_decode_ms": round(warm_decode_ms, 1),
        "wall_ms_first_use": round(model_load_ms + warm_decode_ms, 1),
        "audio_duration_seconds": round(audio_duration, 2),
        "rtf": round(warm_decode_ms / 1000 / audio_duration, 3) if audio_duration else None,
        "segments_returned": len(segments),
        **sampler.summary(),
    }


def _run_sherpa_sensevoice(audio_path: Path, provider: str) -> dict:
    model_path = os.environ.get("ARIAD_SENSEVOICE_MODEL")
    tokens_path = os.environ.get("ARIAD_SENSEVOICE_TOKENS")
    if not model_path or not tokens_path or not Path(model_path).exists() or not Path(tokens_path).exists():
        return {
            "skipped": True,
            "reason": (
                "ARIAD_SENSEVOICE_MODEL/ARIAD_SENSEVOICE_TOKENS not set or files missing -- "
                "download a SenseVoice int8 onnx model from the sherpa-onnx project's own "
                "model releases (same source as the whisper/pyannote models already documented "
                "in README.md) and set both env vars to try this candidate."
            ),
        }
    import sherpa_onnx

    try:
        load_start = time.perf_counter()
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model_path, tokens=tokens_path, provider=provider,
            num_threads=int(os.environ.get("ARIAD_SHERPA_NUM_THREADS", "0")) or (os.cpu_count() or 2),
        )
        model_load_ms = (time.perf_counter() - load_start) * 1000
    except Exception as exc:
        return {"skipped": True, "reason": f"from_sense_voice() failed: {type(exc).__name__}: {exc}"}

    import numpy as np

    with wave.open(str(audio_path)) as w:
        sample_rate = w.getframerate()
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    audio_duration = len(frames) / sample_rate

    with UtilizationSampler() as sampler:
        decode_start = time.perf_counter()
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, frames)
        recognizer.decode_stream(stream)
        warm_decode_ms = (time.perf_counter() - decode_start) * 1000

    return {
        "skipped": False,
        "cold_run_model_load_ms": round(model_load_ms, 1),
        "warm_decode_ms": round(warm_decode_ms, 1),
        "audio_duration_seconds": round(audio_duration, 2),
        "rtf": round(warm_decode_ms / 1000 / audio_duration, 3) if audio_duration else None,
        "note": "single-pass whole-file decode, no diarization/VAD chunking -- not directly apples-to-apples with the turn-by-turn sherpa-whisper candidate above; see tasks/05 report notes.",
        **sampler.summary(),
    }


def _run_faster_whisper(audio_path: Path, model_size: str, device: str, compute_type: str, beam_size: int) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {
            "skipped": True,
            "reason": "faster-whisper not installed -- apps/api/.venv/bin/pip install faster-whisper",
        }

    try:
        load_start = time.perf_counter()
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        model_load_ms = (time.perf_counter() - load_start) * 1000
    except Exception as exc:
        return {"skipped": True, "reason": f"WhisperModel() construction failed: {type(exc).__name__}: {exc}"}

    audio_duration = _read_wav_duration_seconds(audio_path)

    # Cold decode first (first-use cost, e.g. CUDA context/kernel warmup on
    # top of the CTranslate2 model already being loaded), discarded.
    try:
        segments, _info = model.transcribe(str(audio_path), beam_size=beam_size, language="ko")
        list(segments)
    except Exception as exc:
        return {"skipped": True, "reason": f"cold transcribe() failed: {type(exc).__name__}: {exc}"}

    with UtilizationSampler() as sampler:
        decode_start = time.perf_counter()
        segments, _info = model.transcribe(str(audio_path), beam_size=beam_size, language="ko")
        # tasks/05 item 4: segments is a generator -- must be consumed to
        # completion before the timer stops, or this measures "time to
        # first segment", not real decode time.
        segment_list = list(segments)
        warm_decode_ms = (time.perf_counter() - decode_start) * 1000

    return {
        "skipped": False,
        "cold_run_model_load_ms": round(model_load_ms, 1),
        "warm_decode_ms": round(warm_decode_ms, 1),
        "audio_duration_seconds": round(audio_duration, 2),
        "rtf": round(warm_decode_ms / 1000 / audio_duration, 3) if audio_duration else None,
        "segments_returned": len(segment_list),
        "model_size": model_size, "device": device, "compute_type": compute_type, "beam_size": beam_size,
        **sampler.summary(),
    }


CANDIDATES = {
    "sherpa_whisper_cpu": lambda audio: _run_sherpa_whisper(audio, provider="cpu", ko_mode="ko_only"),
    "sherpa_whisper_cuda": lambda audio: _run_sherpa_whisper(audio, provider="cuda", ko_mode="ko_only"),
    "sherpa_sensevoice_cpu": lambda audio: _run_sherpa_sensevoice(audio, provider="cpu"),
    "sherpa_sensevoice_cuda": lambda audio: _run_sherpa_sensevoice(audio, provider="cuda"),
    "faster_whisper_cpu_int8": lambda audio: _run_faster_whisper(
        audio,
        model_size=os.environ.get("FASTER_WHISPER_MODEL", "small"),
        device="cpu", compute_type="int8",
        beam_size=int(os.environ.get("FASTER_WHISPER_BEAM_SIZE", "5")),
    ),
    "faster_whisper_cuda_fp16": lambda audio: _run_faster_whisper(
        audio,
        model_size=os.environ.get("FASTER_WHISPER_MODEL", "small"),
        device="cuda", compute_type="float16",
        beam_size=int(os.environ.get("FASTER_WHISPER_BEAM_SIZE", "5")),
    ),
}


def main() -> int:
    audio_path_str = os.environ.get("AUDIO")
    if not audio_path_str:
        print("Usage: AUDIO=path/to/file.wav python3 scripts/compare_asr_engines.py [ENGINES=a,b,c]")
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
            print(json.dumps(result, ensure_ascii=False, indent=2))
        print()

    print("=" * 78)
    print("요약 (RTF = warm_decode_ms / audio_duration_ms; 낮을수록 빠름, 목표 <= 0.1)")
    print("=" * 78)
    header = f"{'engine':<24}{'RTF':>8}{'warm_ms':>12}{'gpu_util%':>12}{'cpu_util%':>12}"
    print(header)
    print("-" * len(header))
    for key, result in results.items():
        if result.get("skipped"):
            print(f"{key:<24}{'SKIPPED':>8}")
            continue
        rtf = result.get("rtf")
        warm_ms = result.get("warm_decode_ms")
        gpu_util = result.get("gpu_util_avg_pct")
        cpu_util = result.get("cpu_util_avg_pct")
        print(
            f"{key:<24}"
            f"{(f'{rtf:.3f}' if rtf is not None else '-'):>8}"
            f"{(f'{warm_ms:.0f}' if warm_ms is not None else '-'):>12}"
            f"{(f'{gpu_util:.0f}' if gpu_util is not None else '-'):>12}"
            f"{(f'{cpu_util:.0f}' if cpu_util is not None else '-'):>12}"
        )
    print(
        "\n주의: gpu_util%가 0에 가깝거나 '-'이면 provider=cuda가 구성상 허용되어도 실제로는"
        " GPU에서 연산이 돌지 않은(=CPU로 fallback했거나 이 빌드가 CUDA를 지원하지 않는) 것일"
        " 수 있다 -- '생성 성공'과 '실제 가속'을 혼동하지 말 것."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

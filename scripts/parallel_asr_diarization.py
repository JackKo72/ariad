#!/usr/bin/env python3
"""`AUDIO=path/to/file.wav apps/api/.venv/bin/python scripts/parallel_asr_diarization.py`

tasks/05_ASR_HARDWARE_SPEEDUP.md conclusion 2's untested hypothesis: ASR
(faster-whisper, GPU-bound) and diarization (sherpa-onnx, CPU-bound) use
different hardware, so running them *concurrently* instead of back-to-back
should bring wall time close to max(asr, diarize) instead of their sum --
estimated RTF ~0.17 instead of ~0.25 on the real hardware this was
measured on. This script actually tries it and reports whether real
overlap happens, rather than assuming the Python GIL won't block it.

Measures, on the same warm models (no cold-start cost in any of these):
  - Sequential baseline: diarize, then ASR, back to back.
  - Parallel: the same two operations started at the same instant (via a
    threading.Barrier) in two threads. Each operation's own start/end
    timestamp (relative to the shared start) is printed, so the actual
    overlap window is visible directly -- not inferred from whether the
    total got shorter. If the overlap is small, the GIL (or some other
    serialization inside one of the two C++ extensions) is blocking real
    concurrency, and a process-based (not thread-based) redesign would be
    needed instead -- this script reports that finding plainly rather than
    assuming threads would obviously work.
  - GPU/CPU utilization throughout the parallel run (reuses
    scripts/compare_asr_engines.py's UtilizationSampler).

This does not merge diarization output with ASR text -- that integration
is a separate, bigger pipeline change. This only measures whether running
both concurrently is *possible* and *fast* before investing in it.

Never prints decoded text or diarization content -- only counts,
durations, and timestamps. Opt-in, free (no OpenAI call), never part of
`make test`/`make e2e`. Real recordings and their outputs must not be
committed to this repository.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
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


def main() -> int:
    audio_path_str = os.environ.get("AUDIO")
    if not audio_path_str:
        print("Usage: AUDIO=path/to/file.wav python3 scripts/parallel_asr_diarization.py")
        return 1
    audio_path = Path(audio_path_str)
    if not audio_path.exists():
        print(f"File not found: {audio_path}")
        return 1

    _load_env_local()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not installed -- apps/api/.venv/bin/pip install faster-whisper")
        return 1

    import numpy as np
    import sherpa_onnx

    from app.audio.preprocess import standardize_audio
    from app.providers.sherpa_onnx_asr import _model_paths, models_available
    from compare_asr_engines import UtilizationSampler

    models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
    if not models_available(models_dir):
        print(f"sherpa-onnx model files not found under {models_dir!r}. See README.md.")
        return 1

    model_size = os.environ.get("FASTER_WHISPER_MODEL", "large-v3")
    device = os.environ.get("FASTER_WHISPER_DEVICE", "cuda")
    compute_type = os.environ.get("FASTER_WHISPER_COMPUTE_TYPE", "float16" if device == "cuda" else "int8")
    beam_size = int(os.environ.get("FASTER_WHISPER_BEAM_SIZE", "5"))
    # Default cpu -- tasks/05 already confirmed GPU makes diarization
    # slower, not faster. Override only to re-test that finding.
    diarize_provider = os.environ.get("ARIAD_SHERPA_PROVIDER", "cpu")
    num_threads = int(os.environ.get("ARIAD_SHERPA_NUM_THREADS", "0")) or (os.cpu_count() or 2)

    print(f"audio: {audio_path}")
    print(f"ASR: faster-whisper {model_size} device={device} compute_type={compute_type} beam_size={beam_size}")
    print(f"diarization: sherpa-onnx provider={diarize_provider} num_threads={num_threads}\n")

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "16k.wav"
        standardize_audio(audio_path, wav_path, "none")
        with wave.open(str(wav_path)) as w:
            sample_rate = w.getframerate()
            frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    audio_duration = len(frames) / sample_rate
    print(f"audio_duration_seconds: {audio_duration:.2f}\n")

    print("[1/3] Loading + warming models (cold run, discarded) ...")
    paths = _model_paths(models_dir)
    diar_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(paths["segmentation"]))
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(paths["embedding"]), num_threads=2, provider=diarize_provider
        ),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.6),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    try:
        diarizer = sherpa_onnx.OfflineSpeakerDiarization(diar_config)
    except Exception as exc:
        print(f"OfflineSpeakerDiarization() construction failed: {type(exc).__name__}: {exc}")
        return 1
    try:
        whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as exc:
        print(f"WhisperModel() construction failed: {type(exc).__name__}: {exc}")
        print("(if this is a CUDA error, try FASTER_WHISPER_DEVICE=cpu FASTER_WHISPER_COMPUTE_TYPE=int8)")
        return 1

    diarizer.process(frames)  # cold warm-up, discarded
    list(whisper_model.transcribe(str(audio_path), beam_size=beam_size, language="ko")[0])

    print("[2/3] Sequential baseline (diarize, then ASR, same warm models) ...")
    seq_start = time.perf_counter()
    diar_start = time.perf_counter()
    diar_turns = len(diarizer.process(frames).sort_by_start_time())
    diar_ms = (time.perf_counter() - diar_start) * 1000

    asr_start = time.perf_counter()
    segments, _info = whisper_model.transcribe(str(audio_path), beam_size=beam_size, language="ko")
    asr_segment_count = len(list(segments))
    asr_ms = (time.perf_counter() - asr_start) * 1000
    seq_total_ms = (time.perf_counter() - seq_start) * 1000
    print(f"  diarize: {diar_ms:.1f}ms ({diar_turns} turns)")
    print(f"  asr:     {asr_ms:.1f}ms ({asr_segment_count} segments)")
    print(f"  sequential total: {seq_total_ms:.1f}ms\n")

    print("[3/3] Parallel run (diarize + ASR started at the same instant) ...")
    barrier = threading.Barrier(2)
    results: dict = {}

    def _diarize_task() -> None:
        barrier.wait()
        t0 = time.perf_counter()
        n = len(diarizer.process(frames).sort_by_start_time())
        results["diarize"] = {"start": t0, "end": time.perf_counter(), "n": n}

    def _asr_task() -> None:
        barrier.wait()
        t0 = time.perf_counter()
        segs, _ = whisper_model.transcribe(str(audio_path), beam_size=beam_size, language="ko")
        n = len(list(segs))
        results["asr"] = {"start": t0, "end": time.perf_counter(), "n": n}

    with UtilizationSampler() as sampler:
        parallel_wall_start = time.perf_counter()
        t_diarize = threading.Thread(target=_diarize_task)
        t_asr = threading.Thread(target=_asr_task)
        t_diarize.start()
        t_asr.start()
        t_diarize.join()
        t_asr.join()
        parallel_wall_ms = (time.perf_counter() - parallel_wall_start) * 1000

    diar_r = results["diarize"]
    asr_r = results["asr"]
    ref = parallel_wall_start
    print(
        f"  diarize: started +{(diar_r['start'] - ref) * 1000:.1f}ms, "
        f"ended +{(diar_r['end'] - ref) * 1000:.1f}ms ({diar_r['n']} turns)"
    )
    print(
        f"  asr:     started +{(asr_r['start'] - ref) * 1000:.1f}ms, "
        f"ended +{(asr_r['end'] - ref) * 1000:.1f}ms ({asr_r['n']} segments)"
    )
    overlap_start = max(diar_r["start"], asr_r["start"])
    overlap_end = min(diar_r["end"], asr_r["end"])
    overlap_ms = max(0.0, (overlap_end - overlap_start) * 1000)
    print(f"  overlap window: {overlap_ms:.1f}ms")
    print(f"  parallel wall time: {parallel_wall_ms:.1f}ms")
    print(f"  utilization during parallel run: {sampler.summary()}")

    print("\n" + "=" * 70)
    print("요약")
    print("=" * 70)
    seq_rtf = (seq_total_ms / 1000) / audio_duration if audio_duration else float("nan")
    par_rtf = (parallel_wall_ms / 1000) / audio_duration if audio_duration else float("nan")
    print(f"sequential: {seq_total_ms:.0f}ms  (RTF {seq_rtf:.3f})")
    print(f"parallel:   {parallel_wall_ms:.0f}ms  (RTF {par_rtf:.3f})")
    speedup = seq_total_ms / parallel_wall_ms if parallel_wall_ms else float("nan")
    print(f"speedup: {speedup:.2f}x")

    shorter_task_ms = min(diar_ms, asr_ms)
    if overlap_ms < 0.5 * shorter_task_ms:
        print(
            "\n결론: overlap window가 둘 중 짧은 작업 시간의 절반도 안 됨 -- "
            "실제로는 거의 겹치지 않았다(GIL 등으로 직렬화된 것으로 보임). "
            "스레드 기반 병렬화는 이 조합에서 효과가 없다 -- 별도 프로세스 기반"
            "(multiprocessing) 재설계가 필요할 것으로 보임. tasks/05 결론 2를"
            "이 결과로 업데이트할 것."
        )
    else:
        print(
            "\n결론: 두 작업이 실제로 겹쳐 돌았다 -- 스레드 기반 병렬 실행이 이"
            "조합에서 유효함을 확인. 위 parallel RTF x 600을 10분 환산치로 쓸 것."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

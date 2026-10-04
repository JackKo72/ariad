#!/usr/bin/env python3
"""`AUDIO=path/to/file.wav apps/api/.venv/bin/python scripts/parallel_asr_diarization_mp.py`

scripts/parallel_asr_diarization.py's threaded attempt at running ASR
(faster-whisper, GPU) and diarization (sherpa-onnx, CPU) concurrently
showed speedup ~1.00x on real hardware -- the diarization call appears to
hold the GIL for its whole ~65s of C++ compute, blocking the ASR thread's
Python-level progress almost entirely (the ASR thread's own end timestamp
landed almost exactly at diarize's end + ASR's own solo duration, the
signature of near-total serialization despite both threads having
"started" and shown overlapping wall-clock windows).

This retries the same idea with separate OS processes instead of threads,
which have no shared GIL to contend over. Each worker process builds and
warms its own model (full cost, since model objects generally aren't
shareable across a process boundary), then both wait on a
multiprocessing.Barrier so the actual timed work starts at the same
instant in both -- exactly mirroring the threaded script's warm-then-sync
design, just across processes.

Also runs its own single-process sequential baseline first (same models,
same file) so this script's parallel number has a same-run comparison
point, then frees that baseline's models (del + gc.collect()) before
spawning the two workers -- otherwise the baseline's own ~5GB+ VRAM
footprint (large-v3 fp16) would still be held while the child ASR process
tries to load its own copy, risking an OOM on an 8GB card.

Uses the "spawn" multiprocessing start method explicitly (not "fork",
which is unsafe to mix with CUDA) -- this is why worker functions are
plain module-level functions, not closures: spawn re-imports this module
in each child process.

Never prints decoded text or diarization content -- only counts,
durations, and timestamps. Opt-in, free (no OpenAI call), never part of
`make test`/`make e2e`. Real recordings and their outputs must not be
committed to this repository.
"""

from __future__ import annotations

import gc
import multiprocessing as mp
import os
import sys
import tempfile
import time
import wave
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


def _build_diarizer(models_dir: str, provider: str):
    import sherpa_onnx

    from app.providers.sherpa_onnx_asr import _model_paths

    paths = _model_paths(models_dir)
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(paths["segmentation"]))
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(paths["embedding"]), num_threads=2, provider=provider
        ),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.6),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    return sherpa_onnx.OfflineSpeakerDiarization(config)


def _diarize_worker(models_dir: str, provider: str, frames, barrier, result_queue) -> None:
    """Module-level (not a closure) so it's picklable under the "spawn"
    multiprocessing start method -- builds+warms its own diarizer, then
    waits at the barrier before the timed call."""
    diarizer = _build_diarizer(models_dir, provider)
    diarizer.process(frames)  # cold warm-up, discarded

    barrier.wait()
    t0 = time.perf_counter()
    n = len(diarizer.process(frames).sort_by_start_time())
    t1 = time.perf_counter()
    result_queue.put(("diarize", t0, t1, n))


def _asr_worker(
    audio_path: str, model_size: str, device: str, compute_type: str, beam_size: int, barrier, result_queue
) -> None:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    list(model.transcribe(audio_path, beam_size=beam_size, language="ko")[0])  # cold warm-up, discarded

    barrier.wait()
    t0 = time.perf_counter()
    segs, _info = model.transcribe(audio_path, beam_size=beam_size, language="ko")
    n = len(list(segs))
    t1 = time.perf_counter()
    result_queue.put(("asr", t0, t1, n))


def main() -> int:
    audio_path_str = os.environ.get("AUDIO")
    if not audio_path_str:
        print("Usage: AUDIO=path/to/file.wav python3 scripts/parallel_asr_diarization_mp.py")
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

    from app.audio.preprocess import standardize_audio
    from app.providers.sherpa_onnx_asr import models_available

    models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
    if not models_available(models_dir):
        print(f"sherpa-onnx model files not found under {models_dir!r}. See README.md.")
        return 1

    model_size = os.environ.get("FASTER_WHISPER_MODEL", "large-v3")
    device = os.environ.get("FASTER_WHISPER_DEVICE", "cuda")
    compute_type = os.environ.get("FASTER_WHISPER_COMPUTE_TYPE", "float16" if device == "cuda" else "int8")
    beam_size = int(os.environ.get("FASTER_WHISPER_BEAM_SIZE", "5"))
    diarize_provider = os.environ.get("ARIAD_SHERPA_PROVIDER", "cpu")

    print(f"audio: {audio_path}")
    print(f"ASR: faster-whisper {model_size} device={device} compute_type={compute_type} beam_size={beam_size}")
    print(f"diarization: sherpa-onnx provider={diarize_provider}\n")

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "16k.wav"
        standardize_audio(audio_path, wav_path, "none")
        with wave.open(str(wav_path)) as w:
            sample_rate = w.getframerate()
            frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    audio_duration = len(frames) / sample_rate
    print(f"audio_duration_seconds: {audio_duration:.2f}\n")

    print("[1/2] Sequential baseline (single process, same warm models) ...")
    try:
        diarizer = _build_diarizer(models_dir, diarize_provider)
    except Exception as exc:
        print(f"OfflineSpeakerDiarization() construction failed: {type(exc).__name__}: {exc}")
        return 1
    try:
        whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as exc:
        print(f"WhisperModel() construction failed: {type(exc).__name__}: {exc}")
        print("(if this is a CUDA error, try FASTER_WHISPER_DEVICE=cpu FASTER_WHISPER_COMPUTE_TYPE=int8)")
        return 1

    diarizer.process(frames)  # warm-up, discarded
    list(whisper_model.transcribe(str(audio_path), beam_size=beam_size, language="ko")[0])

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
    print(f"  sequential total: {seq_total_ms:.1f}ms")

    # Free this baseline's GPU memory before the child ASR process tries to
    # load its own copy of the same (potentially several-GB) model.
    del diarizer, whisper_model
    gc.collect()
    print("  (freed baseline models before spawning worker processes)\n")

    print("[2/2] Parallel run (separate processes, no shared GIL) ...")
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    result_queue = ctx.Queue()

    p_diarize = ctx.Process(
        target=_diarize_worker, args=(models_dir, diarize_provider, frames, barrier, result_queue)
    )
    p_asr = ctx.Process(
        target=_asr_worker, args=(str(audio_path), model_size, device, compute_type, beam_size, barrier, result_queue)
    )
    p_diarize.start()
    p_asr.start()

    results: dict = {}
    for _ in range(2):
        label, t0, t1, n = result_queue.get()
        results[label] = {"start": t0, "end": t1, "n": n}
    p_diarize.join()
    p_asr.join()

    diar_r = results["diarize"]
    asr_r = results["asr"]
    common_start = min(diar_r["start"], asr_r["start"])
    parallel_wall_ms = (max(diar_r["end"], asr_r["end"]) - common_start) * 1000
    print(
        f"  diarize: started +{(diar_r['start'] - common_start) * 1000:.1f}ms, "
        f"ended +{(diar_r['end'] - common_start) * 1000:.1f}ms ({diar_r['n']} turns)"
    )
    print(
        f"  asr:     started +{(asr_r['start'] - common_start) * 1000:.1f}ms, "
        f"ended +{(asr_r['end'] - common_start) * 1000:.1f}ms ({asr_r['n']} segments)"
    )
    print(f"  parallel wall time: {parallel_wall_ms:.1f}ms")

    print("\n" + "=" * 70)
    print("요약")
    print("=" * 70)
    seq_rtf = (seq_total_ms / 1000) / audio_duration if audio_duration else float("nan")
    par_rtf = (parallel_wall_ms / 1000) / audio_duration if audio_duration else float("nan")
    print(f"sequential (단일 프로세스): {seq_total_ms:.0f}ms  (RTF {seq_rtf:.3f})")
    print(f"parallel (별도 프로세스):   {parallel_wall_ms:.0f}ms  (RTF {par_rtf:.3f})")
    speedup = seq_total_ms / parallel_wall_ms if parallel_wall_ms else float("nan")
    print(f"speedup: {speedup:.2f}x")

    if speedup < 1.3:
        print(
            f"\n결론: speedup {speedup:.2f}x -- 별도 프로세스로도 실질적인 속도 "
            "향상이 없다. GIL이 원인이 아니었다는 뜻 -- 다른 자원 경쟁(디스크 I/O, "
            "CUDA 드라이버 초기화, CPU 메모리 대역폭 등)이 있는지 추가 조사 필요."
        )
    else:
        print(
            f"\n결론: speedup {speedup:.2f}x -- 별도 프로세스 기반 병렬 실행이 "
            "실질적으로 유효함을 확인(스레드로는 안 됐지만 프로세스로는 됨 -- "
            "GIL이 원인이었다는 뜻). 위 parallel RTF x 600을 10분 환산치로 쓸 것. "
            "실제 파이프라인에 적용하려면 app/dependencies.py의 provider 캐싱과 "
            "함께 별도 worker process 설계가 필요하다(추가 구현 필요, 미완료)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

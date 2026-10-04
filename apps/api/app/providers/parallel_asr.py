"""Path B (tasks/05_ASR_HARDWARE_SPEEDUP.md): diarization (sherpa-onnx,
CPU) and ASR (faster-whisper large-v3, CUDA) run in two persistent worker
*processes* instead of sequentially in one. scripts/parallel_asr_diarization.py
proved threads don't help here (the GIL serializes sherpa-onnx's diarization
call against faster-whisper's progress, measured speedup ~1.00x on real
hardware); scripts/parallel_asr_diarization_mp.py proved separate OS
processes do (measured speedup 1.44x, RTF 0.169 on a real 6-minute file).
This module promotes that validated design into a real ASRProvider.

Opt-in only (ARIAD_ASR_ENGINE=parallel_fw_cuda in app.dependencies) --
SherpaOnnxASRProvider stays the unchanged default. Not adopted as the
default here because tasks/05's own accuracy measurement found
faster-whisper large-v3 drops at least one real negation marker
("시작하지 않습니다" -> "시작하기란 습니다") that sherpa-onnx's ko_only mode
preserves -- a clinical-safety regression that needs a paired downstream
mitigation (e.g. apps/api/app/pipeline/enrichment_validation.py's existing
negation guard) before this can be promoted, not just a speed win.

Worker processes are started lazily (first transcribe() call) and kept
alive for the provider's lifetime -- same model-caching philosophy as
SherpaOnnxASRProvider._ensure_models_loaded, just one process per engine
instead of one instance attribute per model. Uses multiprocessing's
"spawn" start method explicitly (not "fork", which is unsafe to mix with
an already-initialized CUDA context) -- worker loop functions are
module-level (not closures) because spawn re-imports this module in each
child process and must be able to pickle the target callable.

Never logs or queues decoded text/audio content beyond what's needed to
produce the transcript itself; diagnostics carries counts/durations only,
matching SherpaOnnxASRProvider's existing convention.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import tempfile
import threading
import time
import wave
from contextlib import nullcontext
from pathlib import Path
from queue import Empty
from typing import Optional

from app.domain.errors import AsrProviderFailed
from app.domain.models import AudioAsset, DiarizedSegment
from app.observability import StageTimer
from app.providers.sherpa_onnx_asr import (
    DEFAULT_MODELS_DIR,
    DiarizationTurn,
    build_diarizer,
    build_vad_config,
    compute_speech_seconds,
    is_garbage_text,
    merge_adjacent_same_speaker,
    merge_diarization_turns,
    models_available,
)

logger = logging.getLogger("ariad.audio")

#: Generous on purpose -- real audio here is a clinical consultation
#: (minutes, not hours), and tasks/05's own measurements put a 6-minute
#: file's diarization+ASR well under 2 minutes even run separately. A
#: timeout this large only ever fires on a genuinely stuck/crashed worker,
#: never on a slow-but-progressing one.
_DEFAULT_RESULT_TIMEOUT_SECONDS = 1800


def _speaker_label(index: int) -> str:
    return chr(ord("A") + index)


def merge_turns_with_asr_segments(turns: list[DiarizationTurn], asr_segments: list[dict]) -> list[dict]:
    """Aligns faster-whisper's own segment boundaries (its own text, no
    speaker) with sherpa-onnx's diarization turns (speaker, no text) by
    timestamp overlap. Each ASR segment's text is assigned to whichever
    turn it overlaps the most; a segment with no temporal overlap at all
    (diarization missed that stretch) falls back to the nearest turn by
    start time rather than being silently dropped. Rows are then built per
    turn, in chronological segment order, skipping turns nothing was
    assigned to. Pure function -- no sherpa_onnx/faster_whisper import, so
    it's unit-testable without either package or real models installed."""
    assigned: dict[int, list[tuple[float, str]]] = {}
    for seg in asr_segments:
        text = seg["text"].strip()
        if not text:
            continue
        seg_start, seg_end = seg["start"], seg["end"]
        best_index: Optional[int] = None
        best_overlap = 0.0
        for i, turn in enumerate(turns):
            overlap = min(seg_end, turn.end) - max(seg_start, turn.start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_index = i
        if best_index is None and turns:
            best_index = min(range(len(turns)), key=lambda i: abs(turns[i].start - seg_start))
        if best_index is None:
            continue
        assigned.setdefault(best_index, []).append((seg_start, text))

    rows: list[dict] = []
    for i, turn in enumerate(turns):
        pieces = assigned.get(i)
        if not pieces:
            continue
        pieces.sort(key=lambda p: p[0])
        text = " ".join(p[1] for p in pieces)
        if not text:
            continue
        rows.append({"start": turn.start, "end": turn.end, "speaker_index": turn.speaker_index, "text": text})
    return rows


def _diarize_worker_loop(models_dir: str, provider: str, num_speakers: int, job_queue, result_queue) -> None:
    """Module-level (not a closure) so it's picklable under the "spawn"
    multiprocessing start method. Builds+warms the diarizer once, then
    serves jobs from job_queue until it receives the None sentinel."""
    diarizer = build_diarizer(models_dir, provider, num_speakers)
    while True:
        job = job_queue.get()
        if job is None:
            break
        job_id = job["job_id"]
        try:
            t0 = time.perf_counter()
            turns = [
                (float(s.start), float(s.end), int(s.speaker))
                for s in diarizer.process(job["frames"]).sort_by_start_time()
            ]
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result_queue.put({"job_id": job_id, "ok": True, "turns": turns, "elapsed_ms": elapsed_ms})
        except Exception as exc:  # pragma: no cover - real-model path, not exercised in CI
            result_queue.put({"job_id": job_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})


def _asr_worker_loop(
    model_size: str, device: str, compute_type: str, beam_size: int, job_queue, result_queue
) -> None:
    """Same contract as _diarize_worker_loop above, for faster-whisper."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    while True:
        job = job_queue.get()
        if job is None:
            break
        job_id = job["job_id"]
        try:
            t0 = time.perf_counter()
            segments, _info = model.transcribe(job["audio_path"], beam_size=beam_size, language="ko")
            seg_list = [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()} for s in segments]
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result_queue.put({"job_id": job_id, "ok": True, "segments": seg_list, "elapsed_ms": elapsed_ms})
        except Exception as exc:  # pragma: no cover - real-model path, not exercised in CI
            result_queue.put({"job_id": job_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})


class ParallelASRProvider:
    """See app.providers.asr_base.ASRProvider. Constructed only when
    ARIAD_ASR_ENGINE=parallel_fw_cuda (app.dependencies); still checks
    sherpa-onnx model files itself, same reasoning as SherpaOnnxASRProvider.

    A lock guards worker-process startup for the same reason
    SherpaOnnxASRProvider guards model loading: FastAPI's sync routes run in
    a threadpool and two requests could race on the very first call."""

    def __init__(
        self,
        models_dir: str | None = None,
        num_speakers: int = 0,
        diarize_provider: str | None = None,
        fw_model_size: str | None = None,
        fw_device: str | None = None,
        fw_compute_type: str | None = None,
        fw_beam_size: int | None = None,
        result_timeout_seconds: float | None = None,
    ):
        self._models_dir = models_dir or os.environ.get("ARIAD_SHERPA_MODELS_DIR", DEFAULT_MODELS_DIR)
        self._num_speakers = num_speakers
        # Default "cpu" -- tasks/05 already measured GPU diarization as
        # slower, not faster, on sherpa-onnx's current API.
        self._diarize_provider = diarize_provider or os.environ.get("ARIAD_SHERPA_PROVIDER", "cpu")
        self._fw_model_size = fw_model_size or os.environ.get("ARIAD_FASTER_WHISPER_MODEL", "large-v3")
        self._fw_device = fw_device or os.environ.get("ARIAD_FASTER_WHISPER_DEVICE", "cuda")
        self._fw_compute_type = fw_compute_type or os.environ.get(
            "ARIAD_FASTER_WHISPER_COMPUTE_TYPE", "float16" if self._fw_device == "cuda" else "int8"
        )
        self._fw_beam_size = fw_beam_size or int(os.environ.get("ARIAD_FASTER_WHISPER_BEAM_SIZE", "5"))
        self._result_timeout_seconds = result_timeout_seconds or _DEFAULT_RESULT_TIMEOUT_SECONDS

        self._start_lock = threading.Lock()
        self._diar_proc: Optional["mp.process.BaseProcess"] = None
        self._asr_proc: Optional["mp.process.BaseProcess"] = None
        self._diar_jobs = None
        self._diar_results = None
        self._asr_jobs = None
        self._asr_results = None
        self._job_counter = 0

    def transcribe(
        self,
        audio_asset: AudioAsset,
        storage_path: str,
        stage_timer: Optional[StageTimer] = None,
        diagnostics: Optional[dict] = None,
    ) -> list[DiarizedSegment]:
        if not models_available(self._models_dir):
            raise AsrProviderFailed(
                f"모델 파일을 찾을 수 없습니다 ({self._models_dir}). README의 모델 다운로드 안내를 확인하세요."
            )
        try:
            return self._transcribe(audio_asset, storage_path, stage_timer, diagnostics)
        except AsrProviderFailed:
            raise
        except Exception as exc:  # pragma: no cover - real-model path, not exercised in CI
            logger.exception("parallel ASR failed for audio_asset_id=%s", audio_asset.id)
            raise AsrProviderFailed(type(exc).__name__) from exc

    def _ensure_workers_started(self) -> None:
        if self._diar_proc is not None and self._diar_proc.is_alive():
            return
        with self._start_lock:
            if self._diar_proc is not None and self._diar_proc.is_alive():
                return  # lost the race, another thread already started them
            try:
                import faster_whisper  # noqa: F401
            except ImportError as exc:
                raise AsrProviderFailed(
                    "faster-whisper가 설치되지 않았습니다. ARIAD_ASR_ENGINE=parallel_fw_cuda를 쓰려면 "
                    "apps/api/.venv/bin/pip install faster-whisper 를 실행하세요."
                ) from exc

            ctx = mp.get_context("spawn")
            diar_jobs, diar_results = ctx.Queue(), ctx.Queue()
            asr_jobs, asr_results = ctx.Queue(), ctx.Queue()
            diar_proc = ctx.Process(
                target=_diarize_worker_loop,
                args=(self._models_dir, self._diarize_provider, self._num_speakers, diar_jobs, diar_results),
                daemon=True,
            )
            asr_proc = ctx.Process(
                target=_asr_worker_loop,
                args=(
                    self._fw_model_size,
                    self._fw_device,
                    self._fw_compute_type,
                    self._fw_beam_size,
                    asr_jobs,
                    asr_results,
                ),
                daemon=True,
            )
            diar_proc.start()
            asr_proc.start()
            self._diar_proc, self._diar_jobs, self._diar_results = diar_proc, diar_jobs, diar_results
            self._asr_proc, self._asr_jobs, self._asr_results = asr_proc, asr_jobs, asr_results

    def close(self) -> None:
        """Stops both worker processes. Not called anywhere in the running
        app (daemon=True processes die with the parent process already) --
        provided for tests and for a clean shutdown hook if one is added
        later."""
        for jobs, proc in ((self._diar_jobs, self._diar_proc), (self._asr_jobs, self._asr_proc)):
            if jobs is not None and proc is not None and proc.is_alive():
                jobs.put(None)
        for proc in (self._diar_proc, self._asr_proc):
            if proc is not None:
                proc.join(timeout=5)

    def _transcribe(
        self,
        audio_asset: AudioAsset,
        storage_path: str,
        stage_timer: Optional[StageTimer],
        diagnostics: Optional[dict] = None,
    ) -> list[DiarizedSegment]:
        import numpy as np

        from app.audio.preprocess import standardize_audio

        with (
            stage_timer.stage("asr_model_load", provider="parallel_fw_cuda_sherpa_cpu")
            if stage_timer
            else nullcontext()
        ) as meta:
            already_warm = self._diar_proc is not None and self._diar_proc.is_alive()
            self._ensure_workers_started()
            if meta is not None:
                meta["cache_hit"] = already_warm

        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "16k.wav"
            with stage_timer.stage("asr_preprocess", provider="ffmpeg") if stage_timer else nullcontext():
                standardize_audio(Path(storage_path), wav_path, "none")
            with wave.open(str(wav_path)) as w:
                sample_rate = w.getframerate()
                frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
            audio_duration = len(frames) / sample_rate

            self._job_counter += 1
            job_id = self._job_counter
            # Both jobs are submitted before either result is awaited --
            # this is what makes the two worker processes actually run
            # concurrently instead of back-to-back.
            self._diar_jobs.put({"job_id": job_id, "frames": frames, "sample_rate": sample_rate})
            self._asr_jobs.put({"job_id": job_id, "audio_path": str(storage_path)})

            with (
                stage_timer.stage("asr_inference", provider="parallel_fw_cuda_sherpa_cpu")
                if stage_timer
                else nullcontext()
            ) as meta:
                try:
                    diar_result = self._diar_results.get(timeout=self._result_timeout_seconds)
                    asr_result = self._asr_results.get(timeout=self._result_timeout_seconds)
                except Empty as exc:
                    raise AsrProviderFailed("병렬 ASR/화자분리 처리 시간이 초과되었습니다.") from exc
                if not diar_result["ok"]:
                    raise AsrProviderFailed(f"화자분리 실패: {diar_result['error']}")
                if not asr_result["ok"]:
                    raise AsrProviderFailed(f"ASR 실패: {asr_result['error']}")

                raw_turns = [DiarizationTurn(s, e, idx) for (s, e, idx) in diar_result["turns"]]
                turns = merge_diarization_turns(raw_turns)
                rows = merge_turns_with_asr_segments(turns, asr_result["segments"])

                vad_config = build_vad_config(self._models_dir, self._diarize_provider)
                vad_config.sample_rate = sample_rate
                filtered_rows = []
                for row in rows:
                    clip = frames[int(row["start"] * sample_rate) : int(row["end"] * sample_rate)]
                    speech_seconds = compute_speech_seconds(clip, sample_rate, vad_config)
                    if is_garbage_text(row["text"], speech_seconds):
                        continue
                    filtered_rows.append(row)

                if meta is not None:
                    meta["audio_duration_seconds"] = audio_duration

            if diagnostics is not None:
                diagnostics["audio_duration_seconds"] = audio_duration
                diagnostics["diarize_ms"] = round(diar_result["elapsed_ms"], 1)
                diagnostics["asr_ms"] = round(asr_result["elapsed_ms"], 1)
                diagnostics["engine"] = "parallel_fw_cuda_sherpa_cpu"

            with stage_timer.stage("asr_postprocess", provider="none") if stage_timer else nullcontext():
                merged_rows = merge_adjacent_same_speaker(filtered_rows)

        return [
            DiarizedSegment(
                id=f"seg_{i + 1:03d}",
                speaker=_speaker_label(row["speaker_index"]),
                role="unknown",
                role_confidence=None,
                start=row["start"],
                end=row["end"],
                text=row["text"],
            )
            for i, row in enumerate(merged_rows)
        ]

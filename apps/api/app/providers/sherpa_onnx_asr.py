"""Real local ASR provider: offline Whisper + pyannote diarization + Silero
VAD via sherpa-onnx (tasks/02_AUDIO_PIPELINE.md section 8, adapted from the
clinician-provided asr_pipeline.py reference script).

Model weights (~GB, Whisper large-v3 in particular) are not bundled and are
not fetched by this code -- GitHub Releases, where sherpa-onnx publishes
them, is unreachable from this development sandbox. Download them on a
machine with normal internet access and point ARIAD_SHERPA_MODELS_DIR at
the directory (see README.md for the exact layout/URLs). transcribe()
checks for the files up front and raises AsrProviderFailed with a clear
message rather than a stack trace if they're missing.

The sherpa_onnx package itself is imported lazily (inside methods, not at
module import time) so this module -- and therefore app.dependencies --
still imports fine in demo-only environments that never installed it.

Pure segment-merging/filtering logic lives in module-level functions with
no sherpa_onnx dependency, so it's unit-testable without real models or the
package installed (see apps/api/tests/test_sherpa_onnx_asr_provider.py).
"""

from __future__ import annotations

import logging
import os
import re
import wave
from pathlib import Path
from typing import NamedTuple

from app.audio.preprocess import standardize_audio
from app.domain.errors import AsrProviderFailed
from app.domain.models import AudioAsset, DiarizedSegment

logger = logging.getLogger("ariad.audio")

DEFAULT_MODELS_DIR = "./models"

# Same hallucination denylist + heuristics as the reference script: short
# filler, punctuation-only, non-Korean-script, or known ASR hallucination
# phrases that stationary-noise/silence tends to produce.
_HALLUCINATION_PHRASES = ["이곳은 한국", "공공기관", "구독", "시청해주셔", "MBC", "KBS 뉴스"]
_NON_KOREAN_RE = re.compile(r"[Ͱ-ϿЀ-ӿ؀-ۿ぀-ヿ一-鿿]")


class DiarizationTurn(NamedTuple):
    start: float
    end: float
    speaker_index: int


def merge_diarization_turns(
    raw_turns: list[DiarizationTurn],
    *,
    max_segment_seconds: float = 28.0,
    merge_gap_seconds: float = 0.8,
) -> list[DiarizationTurn]:
    """Merges adjacent same-speaker turns separated by a short gap, then
    splits anything still longer than max_segment_seconds into roughly
    equal pieces (Whisper's practical single-pass length limit)."""
    merged: list[DiarizationTurn] = []
    for turn in raw_turns:
        if (
            merged
            and merged[-1].speaker_index == turn.speaker_index
            and turn.start - merged[-1].end < merge_gap_seconds
        ):
            merged[-1] = DiarizationTurn(merged[-1].start, turn.end, turn.speaker_index)
        else:
            merged.append(turn)

    split: list[DiarizationTurn] = []
    for turn in merged:
        duration = turn.end - turn.start
        if duration <= max_segment_seconds:
            split.append(turn)
            continue
        pieces = int(-(-duration // max_segment_seconds))  # ceil
        step = duration / pieces
        for i in range(pieces):
            piece_start = turn.start + i * step
            piece_end = min(turn.start + (i + 1) * step, turn.end)
            split.append(DiarizationTurn(piece_start, piece_end, turn.speaker_index))
    return split


def is_garbage_text(text: str, speech_seconds: float) -> bool:
    """True if `text` looks like ASR hallucination rather than real speech:
    near-silence, punctuation only, non-Korean script, or a known
    hallucination phrase."""
    cleaned = text.strip().lstrip("-").strip()
    if speech_seconds < 0.3 or len(cleaned) <= 1:
        return True
    if re.fullmatch(r"[\W_]+", cleaned):
        return True
    if _NON_KOREAN_RE.search(cleaned):
        return True
    return any(phrase in cleaned for phrase in _HALLUCINATION_PHRASES)


def merge_adjacent_same_speaker(
    rows: list[dict], *, gap_seconds: float = 8.0
) -> list[dict]:
    """Final utterance merge: adjacent same-speaker rows within gap_seconds
    become one row, so a clinician reviews natural turns instead of
    Whisper's raw (often choppy) segment boundaries."""
    merged: list[dict] = []
    for row in rows:
        text = row["text"].lstrip("-").strip()
        if merged and merged[-1]["speaker_index"] == row["speaker_index"] and (
            row["start"] - merged[-1]["end"] < gap_seconds
        ):
            merged[-1]["text"] += " " + text
            merged[-1]["end"] = row["end"]
        else:
            merged.append({**row, "text": text})
    return merged


def _speaker_label(index: int) -> str:
    return chr(ord("A") + index)


def _model_paths(models_dir: str) -> dict[str, Path]:
    root = Path(models_dir)
    whisper_dir = root / "sherpa-onnx-whisper-large-v3"
    return {
        "whisper_encoder": whisper_dir / "large-v3-encoder.int8.onnx",
        "whisper_decoder": whisper_dir / "large-v3-decoder.int8.onnx",
        "whisper_tokens": whisper_dir / "large-v3-tokens.txt",
        "segmentation": root / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx",
        "embedding": root / "emb.onnx",
        "vad": root / "silero_vad.onnx",
    }


def models_available(models_dir: str) -> bool:
    return all(path.exists() for path in _model_paths(models_dir).values())


class SherpaOnnxASRProvider:
    """See app.providers.asr_base.ASRProvider. Constructed only when
    ARIAD_MODE=provider (app.dependencies); still checks model files itself
    since "configured" and "models actually present" are different things."""

    def __init__(self, models_dir: str | None = None, num_speakers: int = 0):
        self._models_dir = models_dir or os.environ.get("ARIAD_SHERPA_MODELS_DIR", DEFAULT_MODELS_DIR)
        self._num_speakers = num_speakers

    def transcribe(self, audio_asset: AudioAsset, storage_path: str) -> list[DiarizedSegment]:
        if not models_available(self._models_dir):
            raise AsrProviderFailed(
                f"모델 파일을 찾을 수 없습니다 ({self._models_dir}). README의 모델 다운로드 안내를 확인하세요."
            )

        try:
            return self._transcribe(audio_asset, storage_path)
        except AsrProviderFailed:
            raise
        except Exception as exc:  # pragma: no cover - real-model path, not exercised in CI
            # Traceback only ever names code locations/attribute names, never
            # audio/transcript content (docs/DEBUGGING.md allowed fields) --
            # safe to log in full so a real-model failure is diagnosable
            # instead of collapsing to a bare exception class name.
            logger.exception("sherpa-onnx ASR failed for audio_asset_id=%s", audio_asset.id)
            raise AsrProviderFailed(type(exc).__name__) from exc

    def _transcribe(self, audio_asset: AudioAsset, storage_path: str) -> list[DiarizedSegment]:
        import numpy as np
        import sherpa_onnx

        paths = _model_paths(self._models_dir)

        # Reuse the same standardization Phase B already validated instead
        # of a second bespoke ffmpeg invocation.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "16k.wav"
            standardize_audio(Path(storage_path), wav_path, "none")
            with wave.open(str(wav_path)) as w:
                sample_rate = w.getframerate()
                frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0

            diarization_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                        model=str(paths["segmentation"])
                    )
                ),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(paths["embedding"]), num_threads=2
                ),
                clustering=sherpa_onnx.FastClusteringConfig(
                    num_clusters=self._num_speakers if self._num_speakers > 0 else -1,
                    threshold=0.6 if self._num_speakers <= 0 else 0.5,
                ),
                min_duration_on=0.3,
                min_duration_off=0.5,
            )
            diarizer = sherpa_onnx.OfflineSpeakerDiarization(diarization_config)
            raw_turns = [
                DiarizationTurn(s.start, s.end, int(s.speaker))
                for s in diarizer.process(frames).sort_by_start_time()
            ]
            turns = merge_diarization_turns(raw_turns)

            vad_config = sherpa_onnx.VadModelConfig()
            vad_config.silero_vad.model = str(paths["vad"])
            vad_config.silero_vad.threshold = 0.5
            vad_config.silero_vad.min_speech_duration = 0.15
            vad_config.silero_vad.min_silence_duration = 0.1
            vad_config.sample_rate = sample_rate

            def speech_seconds(clip: "np.ndarray") -> float:
                vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)
                k = 0
                while k + 512 <= len(clip):
                    vad.accept_waveform(clip[k : k + 512])
                    k += 512
                vad.flush()
                total = 0.0
                while not vad.empty():
                    total += len(vad.front.samples) / sample_rate
                    vad.pop()
                return total

            def new_recognizer(language: str) -> "sherpa_onnx.OfflineRecognizer":
                return sherpa_onnx.OfflineRecognizer.from_whisper(
                    encoder=str(paths["whisper_encoder"]),
                    decoder=str(paths["whisper_decoder"]),
                    tokens=str(paths["whisper_tokens"]),
                    num_threads=os.cpu_count() or 2,
                    language=language,
                    task="transcribe",
                )

            recognizer_auto = new_recognizer("")
            recognizer_ko = new_recognizer("ko")

            rows = []
            for turn in turns:
                clip = frames[int(turn.start * sample_rate) : int(turn.end * sample_rate)]
                sv = speech_seconds(clip)
                stream = recognizer_auto.create_stream()
                stream.accept_waveform(sample_rate, clip)
                recognizer_auto.decode_stream(stream)
                text = stream.result.text.strip()

                if _NON_KOREAN_RE.search(text) or (turn.end - turn.start) < 1.2:
                    stream_ko = recognizer_ko.create_stream()
                    stream_ko.accept_waveform(sample_rate, clip)
                    recognizer_ko.decode_stream(stream_ko)
                    text = stream_ko.result.text.strip()

                if is_garbage_text(text, sv):
                    continue
                rows.append({"start": turn.start, "end": turn.end, "speaker_index": turn.speaker_index, "text": text})

        merged_rows = merge_adjacent_same_speaker(rows)
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

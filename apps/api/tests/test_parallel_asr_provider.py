"""Unit: app.providers.parallel_asr (tasks/05_ASR_HARDWARE_SPEEDUP.md Path B).

merge_turns_with_asr_segments is pure (no sherpa_onnx/faster_whisper import)
so it's tested directly, same style as test_sherpa_onnx_asr_provider.py's
pure-function tests. Provider construction/validation is tested without
real models (this sandbox has neither GPU nor faster-whisper installed --
see the module docstring's "opt-in only" framing); the actual 1.44x speedup
this promotes into the pipeline was measured on the user's own hardware via
scripts/parallel_asr_diarization_mp.py, not re-derived here.
"""

import importlib.util

import pytest

from app.domain.errors import AsrProviderFailed
from app.domain.models import AudioAsset
from app.providers.parallel_asr import (
    ParallelASRProvider,
    _ensure_cuda_libs_on_path,
    _speaker_label,
    merge_turns_with_asr_segments,
)
from app.providers.sherpa_onnx_asr import DiarizationTurn

_FIXED_KWARGS = dict(
    id="a", encounter_id="e", kind="original", size_bytes=1, duration_seconds=1.0,
    created_at="2026-01-01T00:00:00+00:00",
)


class TestMergeTurnsWithAsrSegments:
    def test_assigns_segment_text_to_the_overlapping_turn(self):
        turns = [DiarizationTurn(0.0, 5.0, 0), DiarizationTurn(5.0, 10.0, 1)]
        segments = [
            {"start": 0.5, "end": 2.0, "text": "안녕하세요"},
            {"start": 6.0, "end": 8.0, "text": "오늘 혈압이 높아요"},
        ]
        rows = merge_turns_with_asr_segments(turns, segments)
        assert rows == [
            {"start": 0.0, "end": 5.0, "speaker_index": 0, "text": "안녕하세요"},
            {"start": 5.0, "end": 10.0, "speaker_index": 1, "text": "오늘 혈압이 높아요"},
        ]

    def test_joins_multiple_segments_within_one_turn_in_start_order(self):
        turns = [DiarizationTurn(0.0, 10.0, 0)]
        segments = [
            {"start": 5.0, "end": 6.0, "text": "두번째"},
            {"start": 0.0, "end": 1.0, "text": "첫번째"},
        ]
        rows = merge_turns_with_asr_segments(turns, segments)
        assert rows == [{"start": 0.0, "end": 10.0, "speaker_index": 0, "text": "첫번째 두번째"}]

    def test_segment_straddling_two_turns_goes_to_the_larger_overlap(self):
        turns = [DiarizationTurn(0.0, 5.0, 0), DiarizationTurn(5.0, 10.0, 1)]
        # overlaps turn 0 by 1s (4-5) and turn 1 by 3s (5-8) -- should land on turn 1.
        segments = [{"start": 4.0, "end": 8.0, "text": "경계에 걸친 문장"}]
        rows = merge_turns_with_asr_segments(turns, segments)
        assert len(rows) == 1
        assert rows[0]["speaker_index"] == 1

    def test_segment_with_no_overlap_falls_back_to_nearest_turn_by_start(self):
        turns = [DiarizationTurn(0.0, 2.0, 0), DiarizationTurn(20.0, 22.0, 1)]
        # Diarization missed 10-12s entirely -- must not silently drop this text.
        segments = [{"start": 10.0, "end": 12.0, "text": "화자분리가 놓친 구간"}]
        rows = merge_turns_with_asr_segments(turns, segments)
        assert len(rows) == 1
        assert rows[0]["text"] == "화자분리가 놓친 구간"

    def test_turn_with_no_assigned_text_is_dropped(self):
        turns = [DiarizationTurn(0.0, 5.0, 0), DiarizationTurn(5.0, 10.0, 1)]
        segments = [{"start": 0.5, "end": 2.0, "text": "안녕하세요"}]
        rows = merge_turns_with_asr_segments(turns, segments)
        assert len(rows) == 1
        assert rows[0]["speaker_index"] == 0

    def test_blank_segment_text_is_ignored(self):
        turns = [DiarizationTurn(0.0, 5.0, 0)]
        segments = [{"start": 0.0, "end": 1.0, "text": "   "}]
        assert merge_turns_with_asr_segments(turns, segments) == []

    def test_no_turns_returns_empty(self):
        assert merge_turns_with_asr_segments([], [{"start": 0.0, "end": 1.0, "text": "안녕"}]) == []


class TestSpeakerLabel:
    def test_zero_is_a(self):
        assert _speaker_label(0) == "A"

    def test_one_is_b(self):
        assert _speaker_label(1) == "B"


class TestParallelASRProviderConstruction:
    def test_defaults_come_from_env(self, monkeypatch):
        monkeypatch.setenv("ARIAD_SHERPA_PROVIDER", "cpu")
        monkeypatch.setenv("ARIAD_FASTER_WHISPER_MODEL", "large-v3")
        monkeypatch.setenv("ARIAD_FASTER_WHISPER_DEVICE", "cuda")
        monkeypatch.delenv("ARIAD_FASTER_WHISPER_COMPUTE_TYPE", raising=False)
        provider = ParallelASRProvider(models_dir="/does/not/matter")
        assert provider._diarize_provider == "cpu"
        assert provider._fw_model_size == "large-v3"
        assert provider._fw_device == "cuda"
        assert provider._fw_compute_type == "float16"  # cuda default

    def test_cpu_device_defaults_compute_type_to_int8(self, monkeypatch):
        monkeypatch.delenv("ARIAD_FASTER_WHISPER_COMPUTE_TYPE", raising=False)
        provider = ParallelASRProvider(models_dir="/does/not/matter", fw_device="cpu")
        assert provider._fw_compute_type == "int8"

    def test_explicit_kwargs_override_env(self, monkeypatch):
        monkeypatch.setenv("ARIAD_FASTER_WHISPER_MODEL", "large-v3")
        provider = ParallelASRProvider(models_dir="/does/not/matter", fw_model_size="small")
        assert provider._fw_model_size == "small"


class TestParallelASRProviderTranscribe:
    def test_raises_asr_provider_failed_when_models_missing(self, tmp_path):
        provider = ParallelASRProvider(models_dir=str(tmp_path))
        asset = AudioAsset(**_FIXED_KWARGS)
        with pytest.raises(AsrProviderFailed):
            provider.transcribe(asset, str(tmp_path / "audio.wav"))

    def test_raises_clear_error_when_faster_whisper_not_installed(self, tmp_path):
        """This sandbox genuinely has no faster-whisper installed (unlike
        the user's real hardware, which pip-installed it ad hoc during
        tasks/05's investigation) -- a real, not mocked, ImportError path."""
        (tmp_path / "sherpa-onnx-whisper-large-v3").mkdir()
        (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-encoder.int8.onnx").touch()
        (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-decoder.int8.onnx").touch()
        (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-tokens.txt").touch()
        (tmp_path / "sherpa-onnx-pyannote-segmentation-3-0").mkdir()
        (tmp_path / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").touch()
        (tmp_path / "emb.onnx").touch()
        (tmp_path / "silero_vad.onnx").touch()

        provider = ParallelASRProvider(models_dir=str(tmp_path))
        asset = AudioAsset(**_FIXED_KWARGS)
        with pytest.raises(AsrProviderFailed, match="faster-whisper"):
            provider.transcribe(asset, str(tmp_path / "audio.wav"))


class TestEnsureCudaLibsOnPath:
    """Real bug (2026-10-04 user report): faster-whisper's CUDA path raised
    'Library libcublas.so.12 is not found or cannot be loaded' from inside
    this worker process, even though the same CUDA call worked when the
    user ran it as a plain script -- the worker didn't inherit whatever
    LD_LIBRARY_PATH the interactive shell had. This sandbox has no
    nvidia-cublas-cu12 installed (no GPU), so the real dlopen fix can't be
    exercised end-to-end here; these tests cover the path-resolution logic
    itself via a faked importlib.util.find_spec, and the genuine no-op when
    nothing is installed."""

    def test_noop_when_nvidia_packages_not_installed(self, monkeypatch):
        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
        _ensure_cuda_libs_on_path()  # must not raise, must not invent a path
        assert "LD_LIBRARY_PATH" not in __import__("os").environ

    def test_adds_resolved_lib_dirs_to_ld_library_path(self, monkeypatch, tmp_path):
        cublas_dir = str(tmp_path / "nvidia" / "cublas" / "lib")
        cudnn_dir = str(tmp_path / "nvidia" / "cudnn" / "lib")

        def fake_find_spec(name):
            if name == "nvidia.cublas.lib":
                return type("Spec", (), {"submodule_search_locations": [cublas_dir]})()
            if name == "nvidia.cudnn.lib":
                return type("Spec", (), {"submodule_search_locations": [cudnn_dir]})()
            return None

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)

        _ensure_cuda_libs_on_path()

        import os

        updated = os.environ["LD_LIBRARY_PATH"]
        assert cublas_dir in updated
        assert cudnn_dir in updated

    def test_does_not_duplicate_dirs_already_present(self, monkeypatch, tmp_path):
        cublas_dir = str(tmp_path / "nvidia" / "cublas" / "lib")

        def fake_find_spec(name):
            if name == "nvidia.cublas.lib":
                return type("Spec", (), {"submodule_search_locations": [cublas_dir]})()
            return None

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        monkeypatch.setenv("LD_LIBRARY_PATH", cublas_dir)

        _ensure_cuda_libs_on_path()

        import os

        assert os.environ["LD_LIBRARY_PATH"] == cublas_dir

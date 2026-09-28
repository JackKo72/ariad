"""Regression: a real m4a clinical recording crashed
scripts/compare_asr_engines.py's faster-whisper/SenseVoice candidates --
they computed audio duration via wave.open(), which is WAV-only and raises
wave.Error("file does not start with RIFF id") on m4a. The sherpa-onnx
candidates never hit this because SherpaOnnxASRProvider converts internally
via ffmpeg first.

Uses a synthetic (CLAUDE.md: no real patient data) m4a transcoded at test
time from the existing sample_consultation.wav fixture -- never committed
as a new binary fixture."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SOURCE_WAV = REPO_ROOT / "tests" / "fixtures" / "audio" / "sample_consultation.wav"


def _ffmpeg_available() -> bool:
    import shutil

    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture()
def synthetic_m4a(tmp_path) -> Path:
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available in this environment")
    m4a_path = tmp_path / "synthetic.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(SOURCE_WAV), "-c:a", "aac", str(m4a_path)],
        capture_output=True, check=True,
    )
    return m4a_path


def _import_compare_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    import compare_asr_engines  # noqa: PLC0415

    return compare_asr_engines


def test_audio_duration_seconds_handles_m4a_not_just_wav(synthetic_m4a):
    module = _import_compare_module()
    duration = module._audio_duration_seconds(synthetic_m4a)
    assert duration == pytest.approx(59.54, abs=1.0)


def test_audio_duration_seconds_raises_wave_error_was_the_bug(synthetic_m4a):
    """Documents the exact failure this fixes: wave.open() on a non-WAV
    file raises wave.Error, not a friendlier exception."""
    import wave

    with pytest.raises(wave.Error):
        with wave.open(str(synthetic_m4a)):
            pass


def test_load_pcm_via_ffmpeg_handles_m4a(synthetic_m4a):
    module = _import_compare_module()
    frames, sample_rate, duration = module._load_pcm_via_ffmpeg(synthetic_m4a)
    assert sample_rate > 0
    assert len(frames) > 0
    assert duration == pytest.approx(59.54, abs=1.0)

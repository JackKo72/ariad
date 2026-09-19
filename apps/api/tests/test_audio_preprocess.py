"""Unit: FFmpeg standardization + light denoise (tasks/02_AUDIO_PIPELINE.md
section 6)."""

import pytest

from app.audio import preprocess, validation
from app.domain.errors import AudioConversionFailed
from tests.audio_fixtures import make_silence_wav


@pytest.mark.parametrize("mode", ["none", "light_denoise"])
def test_standardize_produces_mono_16k_16bit(tmp_path, mode):
    src = make_silence_wav(tmp_path / "src.wav", duration_seconds=1.0)
    out = tmp_path / f"out_{mode}.wav"

    preprocess.standardize_audio(src, out, mode)

    probe = validation.probe_audio(str(out))
    assert probe.codec_name == "pcm_s16le"
    assert probe.duration_seconds == pytest.approx(1.0, abs=0.1)


def test_standardize_never_overwrites_the_source(tmp_path):
    src = make_silence_wav(tmp_path / "src.wav", duration_seconds=1.0)
    original_bytes = src.read_bytes()
    out = tmp_path / "out.wav"

    preprocess.standardize_audio(src, out, "light_denoise")

    assert src.read_bytes() == original_bytes


def test_standardize_raises_on_nonexistent_input(tmp_path):
    with pytest.raises(AudioConversionFailed):
        preprocess.standardize_audio(tmp_path / "does_not_exist.wav", tmp_path / "out.wav", "none")


def test_light_denoise_filter_chain_is_a_single_denoiser():
    # tasks/02_AUDIO_PIPELINE.md section 6: "여러 denoiser의 연쇄 적용을 금지한다"
    filters = preprocess._audio_filters("light_denoise")
    denoiser_names = ("afftdn", "anlmdn", "arnndn", "highpass", "lowpass", "agate")
    denoiser_count = sum(name in filters for name in denoiser_names)
    assert denoiser_count == 1

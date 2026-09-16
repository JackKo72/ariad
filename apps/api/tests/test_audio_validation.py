"""Unit: ffprobe-based validation (tasks/02_AUDIO_PIPELINE.md section 12)."""

import pytest

from app.audio import validation
from app.domain.errors import (
    AudioDurationTooLong,
    AudioProbeFailed,
    AudioStreamMissing,
    AudioUnsupportedFormat,
)
from tests.audio_fixtures import make_silence_wav, make_video_only_mp4


def test_valid_wav_probes_successfully(tmp_path):
    wav_path = make_silence_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    probe = validation.probe_audio(str(wav_path))
    assert probe.duration_seconds == pytest.approx(1.0, abs=0.1)
    validation.validate_probe_result(probe)  # should not raise


def test_extension_is_not_trusted_valid_content_under_wrong_name(tmp_path):
    # A real wav saved with a misleading extension must still pass, because
    # validation reads the actual stream, not the filename.
    misnamed = tmp_path / "not_actually_an_mp3.mp3"
    make_silence_wav(misnamed, duration_seconds=1.0)
    probe = validation.probe_audio(str(misnamed))
    validation.validate_probe_result(probe)  # should not raise


def test_non_media_file_fails_probe(tmp_path):
    fake = tmp_path / "fake.wav"
    fake.write_bytes(b"this is not audio data at all, just text pretending to be one")
    with pytest.raises(AudioProbeFailed):
        validation.probe_audio(str(fake))


def test_video_only_file_has_no_audio_stream(tmp_path):
    video_path = make_video_only_mp4(tmp_path / "video.mp4", duration_seconds=1.0)
    with pytest.raises(AudioStreamMissing):
        validation.probe_audio(str(video_path))


def test_duration_over_limit_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(validation, "MAX_DURATION_MINUTES", 0)
    wav_path = make_silence_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    probe = validation.probe_audio(str(wav_path))
    with pytest.raises(AudioDurationTooLong):
        validation.validate_probe_result(probe)


def test_unsupported_format_and_codec_is_rejected():
    probe = validation.AudioProbeResult(
        duration_seconds=1.0, format_tokens=frozenset({"flv"}), codec_name="nellymoser"
    )
    with pytest.raises(AudioUnsupportedFormat):
        validation.validate_probe_result(probe)


def test_missing_ffprobe_binary_raises_probe_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(validation.shutil, "which", lambda _name: None)
    with pytest.raises(AudioProbeFailed):
        validation.probe_audio(str(tmp_path / "anything.wav"))

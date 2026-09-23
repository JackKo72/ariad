"""Unit: dependencies.py provider-instance caching
(tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 0/1: real providers used to be
constructed fresh on every request; SherpaOnnxASRProvider in particular
would reload Whisper/pyannote/Silero VAD from disk every time)."""

import app.dependencies as deps
from app.domain.models import AudioAsset

_FIXED_KWARGS = dict(
    id="a", encounter_id="e", kind="original", size_bytes=1, duration_seconds=1.0,
    created_at="2026-01-01T00:00:00+00:00",
)


def test_get_llm_provider_returns_the_same_instance_across_calls(monkeypatch):
    monkeypatch.setattr(deps, "_real_llm_provider", None)
    monkeypatch.setattr(deps, "_real_llm_provider_config", None)
    monkeypatch.setenv("ARIAD_MODE", "provider")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.delenv("OPENAI_TEXT_MODEL", raising=False)

    first = deps.get_llm_provider()
    second = deps.get_llm_provider()
    assert first is second


def test_get_llm_provider_rebuilds_only_when_config_actually_changes(monkeypatch):
    monkeypatch.setattr(deps, "_real_llm_provider", None)
    monkeypatch.setattr(deps, "_real_llm_provider_config", None)
    monkeypatch.setenv("ARIAD_MODE", "provider")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.delenv("OPENAI_TEXT_MODEL", raising=False)

    first = deps.get_llm_provider()
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "gpt-4o")
    second = deps.get_llm_provider()
    assert first is not second

    third = deps.get_llm_provider()
    assert second is third


def test_get_llm_provider_falls_back_to_mock_without_leaking_the_cached_real_provider(monkeypatch):
    monkeypatch.setattr(deps, "_real_llm_provider", None)
    monkeypatch.setattr(deps, "_real_llm_provider_config", None)
    monkeypatch.setenv("ARIAD_MODE", "provider")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    real = deps.get_llm_provider()

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fallback = deps.get_llm_provider()
    assert fallback is deps._mock_llm_provider
    assert fallback is not real


def test_get_asr_provider_returns_the_same_instance_across_calls(monkeypatch, tmp_path):
    (tmp_path / "sherpa-onnx-whisper-large-v3").mkdir()
    (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-encoder.int8.onnx").touch()
    (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-decoder.int8.onnx").touch()
    (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-tokens.txt").touch()
    (tmp_path / "sherpa-onnx-pyannote-segmentation-3-0").mkdir()
    (tmp_path / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").touch()
    (tmp_path / "emb.onnx").touch()
    (tmp_path / "silero_vad.onnx").touch()

    monkeypatch.setattr(deps, "_real_asr_provider", None)
    monkeypatch.setattr(deps, "_real_asr_provider_models_dir", None)
    monkeypatch.setenv("ARIAD_MODE", "provider")
    monkeypatch.setenv("ARIAD_SHERPA_MODELS_DIR", str(tmp_path))

    asset = AudioAsset(**_FIXED_KWARGS)
    first = deps.get_asr_provider(asset)
    second = deps.get_asr_provider(asset)
    assert first is second


def test_get_asr_provider_still_uses_demo_for_sample_assets_when_cache_is_warm(monkeypatch, tmp_path):
    """A cached real provider must never shadow the unconditional
    sample-audio-uses-demo rule (tasks/02_AUDIO_PIPELINE.md: "API key 없이
    샘플 음성 사용으로 승인까지 전체 흐름이 동작해야 한다")."""
    (tmp_path / "sherpa-onnx-whisper-large-v3").mkdir()
    (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-encoder.int8.onnx").touch()
    (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-decoder.int8.onnx").touch()
    (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-tokens.txt").touch()
    (tmp_path / "sherpa-onnx-pyannote-segmentation-3-0").mkdir()
    (tmp_path / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").touch()
    (tmp_path / "emb.onnx").touch()
    (tmp_path / "silero_vad.onnx").touch()

    monkeypatch.setattr(deps, "_real_asr_provider", None)
    monkeypatch.setattr(deps, "_real_asr_provider_models_dir", None)
    monkeypatch.setenv("ARIAD_MODE", "provider")
    monkeypatch.setenv("ARIAD_SHERPA_MODELS_DIR", str(tmp_path))

    deps.get_asr_provider(AudioAsset(**_FIXED_KWARGS))  # warm the real-provider cache
    sample_asset = AudioAsset(**{**_FIXED_KWARGS, "sample_id": "sample_consultation"})
    assert deps.get_asr_provider(sample_asset) is deps._demo_asr_provider

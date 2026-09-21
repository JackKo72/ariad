"""Unit: DemoASRProvider / UnavailableASRProvider / provider selection
(tasks/02_AUDIO_PIPELINE.md sections 3.1, 3.2, 8)."""

import pytest

from app.dependencies import get_asr_provider
from app.domain.errors import AsrNotConfigured
from app.domain.models import AudioAsset
from app.providers.demo_asr import DemoASRProvider, sample_is_available
from app.providers.unavailable_asr import UnavailableASRProvider

FIXED_KWARGS = dict(
    id="asset-1",
    encounter_id="enc-1",
    kind="original",
    size_bytes=1000,
    duration_seconds=59.5,
    created_at="2026-01-01T00:00:00+00:00",
)


def test_sample_consultation_fixture_is_available():
    assert sample_is_available("sample_consultation")


def test_demo_provider_reads_sidecar_transcript_for_known_sample():
    asset = AudioAsset(sample_id="sample_consultation", **FIXED_KWARGS)
    segments = DemoASRProvider().transcribe(asset, "unused")
    assert len(segments) == 10
    assert {s.speaker for s in segments} == {"A", "B"}
    assert all(s.role == "unknown" for s in segments)  # never auto-assigned


def test_demo_provider_is_deterministic():
    asset = AudioAsset(sample_id="sample_consultation", **FIXED_KWARGS)
    provider = DemoASRProvider()
    first = provider.transcribe(asset, "unused")
    second = provider.transcribe(asset, "unused")
    assert first == second


def test_demo_provider_rejects_non_sample_asset():
    asset = AudioAsset(sample_id=None, **FIXED_KWARGS)
    with pytest.raises(AsrNotConfigured):
        DemoASRProvider().transcribe(asset, "unused")


def test_demo_provider_rejects_unknown_sample_id():
    asset = AudioAsset(sample_id="does_not_exist", **FIXED_KWARGS)
    with pytest.raises(AsrNotConfigured):
        DemoASRProvider().transcribe(asset, "unused")


def test_unavailable_provider_always_raises():
    asset = AudioAsset(sample_id=None, **FIXED_KWARGS)
    with pytest.raises(AsrNotConfigured):
        UnavailableASRProvider().transcribe(asset, "unused")


def test_provider_selection_uses_demo_for_sample_asset():
    asset = AudioAsset(sample_id="sample_consultation", **FIXED_KWARGS)
    assert isinstance(get_asr_provider(asset), DemoASRProvider)


def test_provider_selection_uses_unavailable_for_arbitrary_asset():
    asset = AudioAsset(sample_id=None, **FIXED_KWARGS)
    assert isinstance(get_asr_provider(asset), UnavailableASRProvider)

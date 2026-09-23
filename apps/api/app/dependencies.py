"""FastAPI dependency wiring: one SQLite connection per request, one shared
mock provider instance (docs/ARCHITECTURE.md: local default provider).

tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 0 found the real providers
(OpenAILLMProvider, SherpaOnnxASRProvider) were being constructed fresh on
every single request -- for the ASR provider in particular this meant
reloading Whisper/pyannote/Silero VAD from disk every time (SherpaOnnxASRProvider
now caches the loaded models on itself, but that only helps if the instance
itself survives across requests). get_llm_provider/get_asr_provider now
cache one instance per (config) for the process lifetime, rebuilding only
if the resolved api_key/model/models_dir actually changes -- trading "an
edited .env.local takes effect on the next request" for "an edited
.env.local takes effect on the next server restart" (--reload already
restarts the process on code changes; local dev tool, not a concurrent
multi-user service, so this is an acceptable trade confirmed with the
project owner)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from app import db
from app.domain.models import AudioAsset
from app.providers.asr_base import ASRProvider
from app.providers.base import LLMProvider
from app.providers.demo_asr import DemoASRProvider
from app.providers.mock import MockLLMProvider
from app.providers.unavailable_asr import UnavailableASRProvider
from app.repositories.sqlite_repo import EncounterRepository

_mock_llm_provider = MockLLMProvider()
_demo_asr_provider = DemoASRProvider()
_unavailable_asr_provider = UnavailableASRProvider()

_real_llm_provider: LLMProvider | None = None
_real_llm_provider_config: tuple[str, str] | None = None

_real_asr_provider: ASRProvider | None = None
_real_asr_provider_models_dir: str | None = None


def get_db_path() -> str:
    return os.environ.get("ARIAD_DB_PATH", "./data/ariad.db")


def get_audio_dir() -> str:
    return os.environ.get("ARIAD_AUDIO_DIR", "./data/audio")


def get_repository() -> Iterator[EncounterRepository]:
    conn = db.connect(get_db_path())
    try:
        yield EncounterRepository(conn)
    finally:
        conn.close()


def _provider_mode_active() -> bool:
    return os.environ.get("ARIAD_MODE") == "provider"


def get_llm_provider() -> LLMProvider:
    global _real_llm_provider, _real_llm_provider_config
    api_key = os.environ.get("OPENAI_API_KEY")
    if _provider_mode_active() and api_key:
        model = os.environ.get("OPENAI_TEXT_MODEL") or "gpt-4o-mini"
        config = (api_key, model)
        if _real_llm_provider is None or _real_llm_provider_config != config:
            from app.providers.openai_llm import OpenAILLMProvider

            _real_llm_provider = OpenAILLMProvider(api_key=api_key, model=model)
            _real_llm_provider_config = config
        return _real_llm_provider
    return _mock_llm_provider


def get_asr_provider(audio_asset: AudioAsset) -> ASRProvider:
    # A sample-library asset always resolves to the demo provider regardless
    # of ARIAD_MODE -- "API key 없이 샘플 음성 사용으로 승인까지 전체 흐름이
    # 동작해야 한다" is unconditional.
    if audio_asset.sample_id:
        return _demo_asr_provider

    global _real_asr_provider, _real_asr_provider_models_dir
    if _provider_mode_active():
        from app.providers.sherpa_onnx_asr import SherpaOnnxASRProvider, models_available

        models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
        if models_available(models_dir):
            if _real_asr_provider is None or _real_asr_provider_models_dir != models_dir:
                _real_asr_provider = SherpaOnnxASRProvider(models_dir=models_dir)
                _real_asr_provider_models_dir = models_dir
            return _real_asr_provider

    return _unavailable_asr_provider

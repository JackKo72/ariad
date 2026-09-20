"""FastAPI dependency wiring: one SQLite connection per request, one shared
mock provider instance (docs/ARCHITECTURE.md: local default provider)."""

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
    api_key = os.environ.get("OPENAI_API_KEY")
    if _provider_mode_active() and api_key:
        from app.providers.openai_llm import OpenAILLMProvider

        model = os.environ.get("OPENAI_TEXT_MODEL") or "gpt-4o-mini"
        return OpenAILLMProvider(api_key=api_key, model=model)
    return _mock_llm_provider


def get_asr_provider(audio_asset: AudioAsset) -> ASRProvider:
    # A sample-library asset always resolves to the demo provider regardless
    # of ARIAD_MODE -- "API key 없이 샘플 음성 사용으로 승인까지 전체 흐름이
    # 동작해야 한다" is unconditional.
    if audio_asset.sample_id:
        return _demo_asr_provider

    if _provider_mode_active():
        from app.providers.sherpa_onnx_asr import SherpaOnnxASRProvider, models_available

        models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
        if models_available(models_dir):
            return SherpaOnnxASRProvider(models_dir=models_dir)

    return _unavailable_asr_provider

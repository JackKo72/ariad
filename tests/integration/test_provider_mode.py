"""Integration: provider-mode selection and LLM-failure handling
(tasks/02_AUDIO_PIPELINE.md section 9, 12: "ASR는 성공하고 LLM만 실패하면
전사를 보존하고 수동 정리로 계속 진행할 수 있게 한다")."""

import pytest

from app.dependencies import get_llm_provider
from app.domain.errors import LlmProviderFailed
from app.main import app


class _AlwaysFailsProvider:
    def generate_json(self, prompt_id, payload):
        raise LlmProviderFailed("simulated_failure")


@pytest.fixture()
def failing_llm_provider():
    app.dependency_overrides[get_llm_provider] = lambda: _AlwaysFailsProvider()
    yield
    app.dependency_overrides.pop(get_llm_provider, None)


def test_llm_failure_preserves_transcript_and_reports_specific_error_code(
    client, failing_llm_provider
):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    transcript = "의사: 혈압약 5mg 하루 한 번 복용하세요.\n환자: 네."
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": transcript})

    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.status_code == 200
    detail = r.json()
    assert detail["encounter"]["status"] == "PROCESSING_FAILED"
    assert detail["encounter"]["error_code"] == "LLM_PROVIDER_FAILED"
    # The transcript must survive the failure untouched.
    assert detail["draft_version"]["transcript_text"] == transcript


def test_retry_after_llm_failure_succeeds_once_the_provider_recovers(client, failing_llm_provider):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(
        f"/encounters/{encounter_id}/input",
        json={"transcript_text": "의사: 안녕하세요."},
    )
    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.json()["encounter"]["status"] == "PROCESSING_FAILED"

    app.dependency_overrides.pop(get_llm_provider, None)  # provider "recovers"
    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.json()["encounter"]["status"] == "REVIEW_REQUIRED"


def test_capabilities_reflects_provider_mode_without_key_or_models(client, monkeypatch):
    monkeypatch.setenv("ARIAD_MODE", "provider")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.get("/system/capabilities")
    body = r.json()
    assert body["mode"] == "provider"
    assert body["asr"] == "unavailable"  # no sherpa-onnx models on disk in CI
    assert body["llm"] == "mock"  # no key -> falls back, app still works


def test_capabilities_reports_openai_llm_when_key_present(client, monkeypatch):
    monkeypatch.setenv("ARIAD_MODE", "provider")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    r = client.get("/system/capabilities")
    body = r.json()
    assert body["llm"] == "openai"
    assert "sk-test" not in str(body)

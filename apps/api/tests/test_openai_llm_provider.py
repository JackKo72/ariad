"""Contract: OpenAILLMProvider (tasks/02_AUDIO_PIPELINE.md section 9, 12).

Mocks the OpenAI client entirely -- never calls the real API in the default
test suite (task 02 requirement). Verifies the adapter correctly converts a
(mocked) structured-output response into our canonical ClinicalStructure/
ExplanationDraft schema, and that SDK errors (timeout/auth/rate-limit/
malformed) all surface as LLM_PROVIDER_FAILED without leaking request/
response content into the error message.
"""

from unittest.mock import MagicMock

import pytest

from app.domain.errors import LlmProviderFailed
from app.domain.models import ClinicalStructure, ExplanationDraft
from app.observability import StageTimer
from app.providers.openai_llm import OpenAILLMProvider


def _provider_with_mock_client():
    provider = OpenAILLMProvider.__new__(OpenAILLMProvider)  # skip __init__'s real OpenAI() construction
    provider._client = MagicMock()
    provider._model = "gpt-4o-mini"
    return provider


def _mock_completion(parsed):
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(parsed=parsed))]
    return completion


def test_structure_transcript_returns_schema_valid_dict():
    provider = _provider_with_mock_client()
    structure = ClinicalStructure(
        problems=[{"text": "혈압 상승", "certainty": "stated", "source_segment_ids": ["seg-1"]}]
    )
    provider._client.chat.completions.parse.return_value = _mock_completion(structure)

    result = provider.generate_json("structure_transcript", {"transcript_text": "의사: ..."})

    assert result == structure.model_dump()
    call_kwargs = provider._client.chat.completions.parse.call_args.kwargs
    assert call_kwargs["response_format"] is ClinicalStructure
    assert call_kwargs["model"] == "gpt-4o-mini"


def test_patient_explanation_returns_schema_valid_dict():
    provider = _provider_with_mock_client()
    explanation = ExplanationDraft(draft_notice="의료진 검토 전 초안입니다.")
    provider._client.chat.completions.parse.return_value = _mock_completion(explanation)

    result = provider.generate_json("patient_explanation", {"structure": {}})

    assert result == explanation.model_dump()


def test_unknown_prompt_id_raises_value_error():
    provider = _provider_with_mock_client()
    with pytest.raises(ValueError):
        provider.generate_json("not_a_real_prompt", {})


def test_none_parsed_result_raises_llm_provider_failed():
    provider = _provider_with_mock_client()
    provider._client.chat.completions.parse.return_value = _mock_completion(None)
    with pytest.raises(LlmProviderFailed):
        provider.generate_json("structure_transcript", {"transcript_text": "..."})


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: __import__("openai").APITimeoutError(request=MagicMock()),
        lambda: __import__("openai").AuthenticationError(
            message="unauthorized", response=MagicMock(headers={}), body=None
        ),
        lambda: __import__("openai").RateLimitError(
            message="rate limited", response=MagicMock(headers={}), body=None
        ),
    ],
)
def test_sdk_errors_map_to_llm_provider_failed_without_leaking_content(exc_factory):
    provider = _provider_with_mock_client()
    provider._client.chat.completions.parse.side_effect = exc_factory()

    with pytest.raises(LlmProviderFailed) as exc_info:
        provider.generate_json("structure_transcript", {"transcript_text": "환자의 실제 민감정보"})

    assert exc_info.value.code == "LLM_PROVIDER_FAILED"
    assert "환자의 실제 민감정보" not in exc_info.value.message


def test_non_ascii_api_key_header_error_raises_actionable_llm_provider_failed():
    """Regression: a real user left the README's example placeholder
    (containing Korean characters) in apps/api/.env.local's OPENAI_API_KEY.
    The SDK raises UnicodeEncodeError deep inside HTTP header construction
    (not an OpenAIError, so the OpenAIError except clause alone doesn't
    catch it) -- this must still surface as a clear, actionable
    LLM_PROVIDER_FAILED instead of a bare traceback."""
    provider = _provider_with_mock_client()
    provider._client.chat.completions.parse.side_effect = UnicodeEncodeError(
        "ascii", "Bearer sk-...실제키...", 13, 16, "ordinal not in range(128)"
    )

    with pytest.raises(LlmProviderFailed) as exc_info:
        provider.generate_json("structure_transcript", {"transcript_text": "..."})

    assert exc_info.value.code == "LLM_PROVIDER_FAILED"
    assert "OPENAI_API_KEY" in exc_info.value.message


def test_clinical_structure_and_explanation_draft_are_openai_strict_schema_compatible():
    """Regression: a real user's ClinicalStructure/ExplanationDraft request
    was rejected by the live API with a 400 BadRequestError ("'required' is
    required to be supplied and to be an array including every key in
    properties") because these models used to declare their nested items as
    dict[str, Any]. OpenAI's strict structured-output mode collapses a free
    -form dict to an object schema with no declared properties, which the
    API then refuses. This doesn't need network access or a real key -- the
    schema-generation mismatch is detectable purely client-side via the
    SDK's own conversion, which is exactly where it should have been caught
    before a user ever hit it live."""
    from openai.lib._parsing._completions import type_to_response_format_param

    for schema_cls in (ClinicalStructure, ExplanationDraft):
        type_to_response_format_param(schema_cls)  # raises if incompatible


def test_stage_timer_records_stage_name_model_and_token_usage():
    """tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1: structure_transcript
    maps to pipeline stage structure_llm (not the prompt_id itself), and
    completion.usage token counts must land on the record when a
    StageTimer is passed."""
    provider = _provider_with_mock_client()
    structure = ClinicalStructure(
        problems=[{"text": "혈압 상승", "certainty": "stated", "source_segment_ids": ["seg-1"]}]
    )
    completion = _mock_completion(structure)
    completion.usage = MagicMock(prompt_tokens=321, completion_tokens=87)
    provider._client.chat.completions.parse.return_value = completion

    timer = StageTimer()
    provider.generate_json("structure_transcript", {"transcript_text": "..."}, stage_timer=timer)

    assert len(timer.records) == 1
    record = timer.records[0]
    assert record.stage == "structure_llm"
    assert record.status == "ok"
    assert record.provider == "openai"
    assert record.model == "gpt-4o-mini"
    assert record.input_tokens == 321
    assert record.output_tokens == 87


def test_stage_timer_records_error_status_on_failure():
    provider = _provider_with_mock_client()
    provider._client.chat.completions.parse.side_effect = __import__("openai").AuthenticationError(
        message="unauthorized", response=MagicMock(headers={}), body=None
    )

    timer = StageTimer()
    with pytest.raises(LlmProviderFailed):
        provider.generate_json("patient_explanation", {"structure": {}}, stage_timer=timer)

    assert len(timer.records) == 1
    record = timer.records[0]
    assert record.stage == "explanation_llm"
    assert record.status == "error"
    assert record.error_code == "LLM_PROVIDER_FAILED"

"""Real text LLM provider (tasks/02_AUDIO_PIPELINE.md section 9).

Implements the same LLMProvider.generate_json(prompt_id, payload) -> dict
boundary MockLLMProvider does, so app/pipeline/{structure,explanation}.py
and the routes that call them need no changes to use this instead. Uses
the OpenAI SDK's structured-output parsing (response_format=<pydantic
model>) bound to the exact schemas in packages/contracts/schema/*.json --
never regexes prose into JSON. The OpenAI client and its exceptions are
imported lazily (inside __init__/methods, not at module import time) so
importing this module -- and therefore app.dependencies -- never requires
the `openai` package to be installed for demo-mode-only environments.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any, Optional

from app.domain.errors import LlmProviderFailed
from app.domain.models import ClinicalEnrichment, ClinicalStructure, ExplanationDraft, TermCandidateList
from app.observability import StageTimer
from app.providers.mock import (
    PROMPT_VERSION_ENRICHMENT,
    PROMPT_VERSION_EXPLANATION,
    PROMPT_VERSION_STRUCTURE,
    PROMPT_VERSION_TERM_CANDIDATES,
)

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"

# Used when OPENAI_TEXT_MODEL is unset. tasks/10 REPEAT=3 evals on the ICU/ER
# role-plays: gpt-4o beat gpt-4o-mini by 13-17 points of recall on both, at
# similar latency (14-16 s), so it is the default; set OPENAI_TEXT_MODEL to
# override (e.g. gpt-4o-mini for cost).
DEFAULT_TEXT_MODEL = "gpt-4o"

# Every call here extracts or rewrites what the transcript says; none needs
# variety. With the API default (1.0) the 13-c REPEAT=3 eval returned 1, 4
# and 10 term candidates for the same MG transcript.
TEMPERATURE = 0
# At temperature 0 a long transcript can fall into a repetition loop that
# runs to the model's output limit (ER role-play: 16,384 tokens, no JSON).
# Normal outputs here are 2-3k tokens, so cap well above that to fail
# sooner and cheaper, then retry once at the API default temperature, which
# never looped in earlier evals. The retry is recorded as the stage's retry_count.
MAX_OUTPUT_TOKENS = 8000
RETRY_TEMPERATURE = 1.0

# prompt_id -> (pipeline stage name, response schema, prompt version).
# tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1 names the pipeline stages
# structure_llm/explanation_llm; prompt_id names the prompt file instead --
# related but distinct, so map explicitly rather than assuming they match.
_CALL_SPEC = {
    "structure_transcript": ("structure_llm", ClinicalStructure, PROMPT_VERSION_STRUCTURE),
    "patient_explanation": ("explanation_llm", ExplanationDraft, PROMPT_VERSION_EXPLANATION),
    "clinical_enrichment": ("clinical_enrichment_llm", ClinicalEnrichment, PROMPT_VERSION_ENRICHMENT),
    "term_candidates": ("term_candidates_llm", TermCandidateList, PROMPT_VERSION_TERM_CANDIDATES),
}


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


class OpenAILLMProvider:
    """See app.providers.base.LLMProvider. Constructed only when
    ARIAD_MODE=provider and OPENAI_API_KEY is set (app.dependencies)."""

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate_json(
        self, prompt_id: str, payload: dict[str, Any], stage_timer: Optional[StageTimer] = None
    ) -> dict[str, Any]:
        spec = _CALL_SPEC.get(prompt_id)
        if spec is None:
            raise ValueError(f"OpenAILLMProvider has no handler for prompt_id={prompt_id!r}")
        stage_name, schema, prompt_version = spec
        return self._call(prompt_id, payload, schema, stage_name, prompt_version, stage_timer)

    def _call(
        self,
        prompt_id: str,
        payload: dict[str, Any],
        schema: type,
        stage_name: str,
        prompt_version: str,
        stage_timer: Optional[StageTimer],
    ) -> dict[str, Any]:
        import json

        from openai import LengthFinishReasonError, OpenAIError

        system_prompt = _load_prompt(prompt_id)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        with (
            stage_timer.stage(stage_name, provider="openai", model=self._model, prompt_version=prompt_version)
            if stage_timer
            else nullcontext()
        ) as meta:
            cut_off_usage = None
            try:
                try:
                    completion = self._parse(messages, schema, TEMPERATURE)
                except LengthFinishReasonError as exc:
                    cut_off_usage = exc.completion.usage
                    if meta is not None:
                        meta["retry_count"] = 1
                    completion = self._parse(messages, schema, RETRY_TEMPERATURE)
            except OpenAIError as exc:
                # Never include the request/response body in the error --
                # only the error class name (docs/DEBUGGING.md: no
                # transcript/explanation content in logs or user-facing
                # error detail).
                raise LlmProviderFailed(type(exc).__name__) from exc
            except UnicodeEncodeError as exc:
                # The SDK raises this deep inside HTTP header construction
                # (not an OpenAIError) when the API key contains non-ASCII
                # characters -- in practice this means apps/api/.env.local
                # still has the README's example placeholder instead of a
                # real key.
                raise LlmProviderFailed(
                    "OPENAI_API_KEY에 ASCII가 아닌 문자가 포함되어 있습니다. "
                    "apps/api/.env.local의 값이 예시 placeholder가 아닌 실제 발급받은 키인지 확인하세요."
                ) from exc

            if meta is not None and completion.usage is not None:
                # Both attempts are billed, so both count.
                usages = [u for u in (cut_off_usage, completion.usage) if u is not None]
                meta["input_tokens"] = sum(u.prompt_tokens for u in usages)
                meta["output_tokens"] = sum(u.completion_tokens for u in usages)

            parsed = completion.choices[0].message.parsed
            if parsed is None:
                raise LlmProviderFailed("empty_response")
            return parsed.model_dump()

    def _parse(self, messages: list[dict[str, str]], schema: type, temperature: float) -> Any:
        return self._client.chat.completions.parse(
            model=self._model,
            messages=messages,
            response_format=schema,
            temperature=temperature,
            max_completion_tokens=MAX_OUTPUT_TOKENS,
        )

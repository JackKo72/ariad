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

from pathlib import Path
from typing import Any

from app.domain.errors import LlmProviderFailed
from app.domain.models import ClinicalStructure, ExplanationDraft

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


class OpenAILLMProvider:
    """See app.providers.base.LLMProvider. Constructed only when
    ARIAD_MODE=provider and OPENAI_API_KEY is set (app.dependencies)."""

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate_json(self, prompt_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if prompt_id == "structure_transcript":
            return self._call(prompt_id, payload, ClinicalStructure)
        if prompt_id == "patient_explanation":
            return self._call(prompt_id, payload, ExplanationDraft)
        raise ValueError(f"OpenAILLMProvider has no handler for prompt_id={prompt_id!r}")

    def _call(self, prompt_id: str, payload: dict[str, Any], schema: type) -> dict[str, Any]:
        import json

        from openai import OpenAIError

        system_prompt = _load_prompt(prompt_id)
        try:
            completion = self._client.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format=schema,
            )
        except OpenAIError as exc:
            # Never include the request/response body in the error -- only
            # the error class name (docs/DEBUGGING.md: no transcript/
            # explanation content in logs or user-facing error detail).
            raise LlmProviderFailed(type(exc).__name__) from exc

        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise LlmProviderFailed("empty_response")
        return parsed.model_dump()

"""Contract: MockLLMProvider output must satisfy packages/contracts/schema/*.json
(docs/TESTING_AND_EVALS.md layer table: Contract = provider mock + JSON schema)."""

import json
from pathlib import Path

import jsonschema

from app.providers.mock import MockLLMProvider

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "schema"
TRANSCRIPT = "의사: 오늘 혈압이 조금 높네요.\n환자: 요즘 짜게 먹었어요."


def _load_schema(name: str) -> dict:
    return json.loads((CONTRACTS_DIR / name).read_text())


def test_structure_transcript_output_matches_schema():
    provider = MockLLMProvider()
    output = provider.generate_json("structure_transcript", {"transcript_text": TRANSCRIPT})
    jsonschema.validate(output, _load_schema("clinical_structure.schema.json"))


def test_patient_explanation_output_matches_schema():
    provider = MockLLMProvider()
    structure = provider.generate_json("structure_transcript", {"transcript_text": TRANSCRIPT})
    output = provider.generate_json("patient_explanation", {"structure": structure})
    jsonschema.validate(output, _load_schema("explanation_draft.schema.json"))

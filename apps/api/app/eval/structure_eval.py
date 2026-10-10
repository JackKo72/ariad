"""tasks/09_STRUCTURE_EVAL_AGAINST_CLINICIAN_GOLD.md: scores LLM
structuring output (clinical_enrichment + structure_transcript JSON)
against a clinician-written gold list of what the summary must contain.

Gold item tiers -- the distinction this whole eval exists for:
  conversation  said in the conversation (often in lay words: "재워놨어요",
                "심장 뛰는 모양이 이상"). Expected from the transcript alone.
  context_only  true for the patient but never said aloud (drug names, test
                names, working diagnoses the clinician knows from the chart:
                "midazolam", "EEG"). CLAUDE.md forbids generating these from
                the transcript, so without clinician context they must be
                ABSENT -- a hit is a hallucination, not a success.
  must_exclude  in the transcript but must never reach the summary:
                background speech from other conversations, profanity,
                off-record remarks. A hit is a leak.

An item matches one output item (one element of any section list) when
that item's text contains at least one alternative from every
`must_match` group. Korean alternatives ignore case and whitespace (ASR and
LLM spacing varies: "할 수도" == "할수도"); ASCII alternatives must stand as
whole words, so "CIN" never matches inside "medicine".

Pure -- see apps/api/tests/test_structure_eval.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _norm(text: str) -> str:
    return "".join(text.lower().split())


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def output_items(output: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """(section, text) per list element, recursing into nested dicts so
    {"enrichment": {...}, "structure": {...}} works as one output."""
    items = []
    for key, value in output.items():
        section = f"{prefix}{key}"
        if isinstance(value, list):
            items += [(section, " ".join(_strings(v))) for v in value]
        elif isinstance(value, dict):
            items += output_items(value, prefix=f"{section}.")
    return items


def _contains(text: str, alternative: str) -> bool:
    if alternative.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(alternative.lower())}(?![a-z0-9])"
        return re.search(pattern, text.lower()) is not None
    return _norm(alternative) in _norm(text)


def matches(text: str, must_match: list[list[str]]) -> bool:
    return all(any(_contains(text, alt) for alt in group) for group in must_match)


@dataclass(frozen=True)
class ItemResult:
    id: str
    tier: str
    hit: bool
    sections: tuple[str, ...]


@dataclass(frozen=True)
class StructureScore:
    items: list[ItemResult]
    conversation_recall: float | None
    # context_only items found in the output while no clinician context was
    # given: generated beyond the transcript.
    context_only_leaks: list[str]
    # must_exclude items found in the output (always a leak).
    excluded_leaks: list[str]
    # Gold self-check against the INPUT text: conversation items whose
    # keywords aren't even in the input (gold spec is wrong) and
    # context_only items whose keywords ARE in the input (mis-tiered).
    gold_errors: list[str]


def score_structure(output: dict[str, Any], gold: dict[str, Any], input_text: str,
                    context_given: bool = False) -> StructureScore:
    items = output_items(output)
    results, gold_errors = [], []
    for item in gold["items"]:
        sections = tuple(sorted({section for section, text in items if matches(text, item["must_match"])}))
        results.append(ItemResult(item["id"], item["tier"], bool(sections), sections))
        in_input = matches(input_text, item["must_match"])
        if item["tier"] == "conversation" and not in_input:
            gold_errors.append(f"{item['id']}: conversation item not found in input")
        if item["tier"] == "context_only" and in_input:
            gold_errors.append(f"{item['id']}: context_only item is present in input")

    conversation = [r for r in results if r.tier == "conversation"]
    recall = sum(r.hit for r in conversation) / len(conversation) if conversation else None
    leaks = [] if context_given else [r.id for r in results if r.tier == "context_only" and r.hit]
    excluded = [r.id for r in results if r.tier == "must_exclude" and r.hit]
    return StructureScore(results, recall, leaks, excluded, gold_errors)

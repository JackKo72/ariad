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
  frame_term    a clinical term for something said in lay words ("혈전을
                끄집어내는 시술" -> EVT), allowed only when the clinician picked
                the matching clinical frame (item "frame": "stroke"). With
                that frame it is expected (frame recall); without it a hit
                is a leak, like context_only.
  must_exclude  in the transcript but must never reach the summary:
                background speech from other conversations, profanity,
                off-record remarks. A hit is a leak.

An item matches one output item (one element of any section list) when
that item's text contains at least one alternative from every
`must_match` group. Korean alternatives ignore case and whitespace (ASR and
LLM spacing varies: "할 수도" == "할수도"); ASCII alternatives must stand as
whole words, so "CIN" never matches inside "medicine".

Term-candidate quotes (tasks/13-c): `term_candidates[].spoken_text` is a
verbatim copy of the transcript, so it contains conversation keywords
without the summary having kept anything. A conversation item found ONLY
there is not a hit (its sections still list it, so it shows as
"miss  structure.term_candidates"). Leak tiers and frame_term still look
at every section, term candidates included.

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
    # frame_term items of the selected frames: share found (None if none
    # selected); frame_term items of unselected frames that appeared leak.
    frame_recall: float | None
    frame_leaks: list[str]
    # Gold self-check against the INPUT text: conversation items whose
    # keywords aren't even in the input (gold spec is wrong) and
    # context_only items whose keywords ARE in the input (mis-tiered).
    gold_errors: list[str]


TERM_CANDIDATE_SECTION = "term_candidates"


def _counts_for(tier: str, section: str) -> bool:
    return tier != "conversation" or not section.endswith(TERM_CANDIDATE_SECTION)


def score_structure(output: dict[str, Any], gold: dict[str, Any], input_text: str,
                    context_given: bool = False, frames: frozenset[str] = frozenset()) -> StructureScore:
    items = output_items(output)
    results, gold_errors = [], []
    for item in gold["items"]:
        sections = tuple(sorted({section for section, text in items if matches(text, item["must_match"])}))
        hit = any(_counts_for(item["tier"], section) for section in sections)
        results.append(ItemResult(item["id"], item["tier"], hit, sections))
        in_input = matches(input_text, item["must_match"])
        if item["tier"] == "conversation" and not in_input:
            gold_errors.append(f"{item['id']}: conversation item not found in input")
        if item["tier"] in ("context_only", "frame_term") and in_input:
            gold_errors.append(f"{item['id']}: context_only item is present in input")

    conversation = [r for r in results if r.tier == "conversation"]
    recall = sum(r.hit for r in conversation) / len(conversation) if conversation else None
    leaks = [] if context_given else [r.id for r in results if r.tier == "context_only" and r.hit]
    excluded = [r.id for r in results if r.tier == "must_exclude" and r.hit]
    frame_of = {item["id"]: item.get("frame") for item in gold["items"]}
    in_frame = [r for r in results if r.tier == "frame_term" and frame_of[r.id] in frames]
    frame_recall = sum(r.hit for r in in_frame) / len(in_frame) if in_frame else None
    frame_leaks = [r.id for r in results if r.tier == "frame_term" and frame_of[r.id] not in frames and r.hit]
    return StructureScore(results, recall, leaks, excluded, frame_recall, frame_leaks, gold_errors)


@dataclass(frozen=True)
class MissDiagnosis:
    """Why a conversation item missed, from gold keywords alone (no output
    text): tasks/13-d.

    kind  partial  one output item has some must_match groups, not all
                   (paraphrased, or part of the fact dropped)
          split    every group appears, but across different output items
          omitted  no counted output item has any group
    best_section / best_groups: the output item matching the most groups.
    in_quote: the whole item is in a term-candidate quote (said, and seen
    by the term call, but not kept by the summary)."""

    id: str
    kind: str
    best_section: str | None
    best_groups: tuple[int, ...]
    in_quote: bool


def _groups_matched(text: str, must_match: list[list[str]]) -> set[int]:
    return {i for i, group in enumerate(must_match) if any(_contains(text, alt) for alt in group)}


def diagnose_miss(output: dict[str, Any], item: dict[str, Any]) -> MissDiagnosis:
    must_match = item["must_match"]
    best_section, best = None, set()
    anywhere: set[int] = set()
    in_quote = False
    for section, text in output_items(output):
        matched = _groups_matched(text, must_match)
        if not _counts_for("conversation", section):
            in_quote = in_quote or len(matched) == len(must_match)
            continue
        anywhere |= matched
        if len(matched) > len(best):
            best_section, best = section, matched
    if not anywhere:
        kind = "omitted"
    elif len(anywhere) == len(must_match) and len(best) < len(must_match):
        kind = "split"
    else:
        kind = "partial"
    return MissDiagnosis(item["id"], kind, best_section, tuple(sorted(best)), in_quote)

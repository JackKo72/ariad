#!/usr/bin/env python3
"""`make check-vocab-leakage [DIR=apps/api/data/annotations]`

tasks/11_NEURO_EXAM_VOCAB_AND_SPLITS.md: frame vocabularies
(prompts/frames/**/*.json) may learn real phrasings from DEVELOPMENT
recordings only. If a phrase from an EVALUATION recording is copied into a
vocabulary, that recording's frame-term score is inflated and stops
measuring anything. This fails when any spoken_example of 3+ words appears
(whitespace-insensitive) in the transcript of a gold marked "split": "eval".
1-2 word examples are standard term names ("내시경 초음파") and may
legitimately occur anywhere. Quoted Korean examples in prompts/*.md are
checked too, from 4 Hangul characters up -- a short prompt example
("재워놨어요") can still hand the model an eval answer (tasks/12).

Reads gold from tests/evals/gold/, transcripts from DIR/<case>.transcript.json
(gitignored data/). Prints only the overlapping vocabulary phrase.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRAMES_DIR = REPO_ROOT / "prompts" / "frames"
GOLD_DIR = REPO_ROOT / "tests" / "evals" / "gold"
MIN_WORDS = 3
PROMPTS_DIR = REPO_ROOT / "prompts"
MIN_PROMPT_HANGUL = 4


def vocabulary_phrases(frames_dir: Path = FRAMES_DIR) -> list[tuple[str, str]]:
    """(file, example) for every sentence-like spoken example."""
    phrases = []
    for path in sorted(frames_dir.rglob("*.json")):
        for term in json.loads(path.read_text(encoding="utf-8")).get("terms", []):
            phrases += [(path.relative_to(frames_dir).as_posix(), ex) for ex in term["spoken_examples"]
                        if len(ex.split()) >= MIN_WORDS]
    return phrases


def prompt_phrases(prompts_dir: Path = PROMPTS_DIR) -> list[tuple[str, str]]:
    """(file, quoted example) for Korean strings quoted in prompt markdown."""
    import re

    phrases = []
    for path in sorted(prompts_dir.glob("*.md")):
        for quote in re.findall(r'"([^"\n]+)"', path.read_text(encoding="utf-8")):
            if sum("\uac00" <= ch <= "\ud7a3" for ch in quote) >= MIN_PROMPT_HANGUL:
                phrases.append((path.name, quote))
    return phrases


def find_overlaps(phrases: list[tuple[str, str]], transcript_text: str) -> list[tuple[str, str]]:
    squashed = "".join(transcript_text.split())
    return [(f, ex) for f, ex in phrases if "".join(ex.split()) in squashed]


def main() -> int:
    data_dir = Path(os.environ.get("DIR", REPO_ROOT / "apps" / "api" / "data" / "annotations"))
    phrases = vocabulary_phrases() + prompt_phrases()
    failed = checked = 0
    for gold_path in sorted(GOLD_DIR.glob("*.gold.json")):
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        if gold.get("split") != "eval":
            continue
        transcript_path = data_dir / f"{gold['case']}.transcript.json"
        if not transcript_path.is_file():
            print(f"[{gold['case']}] transcript not found at {transcript_path} -- skipped")
            continue
        checked += 1
        segments = json.loads(transcript_path.read_text(encoding="utf-8"))["segments"]
        for frame_file, example in find_overlaps(phrases, " ".join(s["text"] for s in segments)):
            failed += 1
            print(f"[{gold['case']}] eval phrase copied into {frame_file}: {example}")
    print(f"{checked} eval transcript(s) checked against {len(phrases)} vocabulary/prompt phrases: "
          f"{'FAIL' if failed else 'OK'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

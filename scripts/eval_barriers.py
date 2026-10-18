"""Evaluate red flag rules and barrier classification (docs/ARIAD_stage2_design.md Step 5).

Two sets in tests/fixtures/barriers/:
- red_flags.json: 10 red flag sentences (must all be caught) + negative
  sentences (false-positive check, reported, not gated).
- responses.json: 50 synthetic free-text reasons, 5 per Part 3-3 code,
  run through build_barrier_report -> confusion matrix.

    python3 scripts/eval_barriers.py            # mock provider
    ARIAD_MODE=provider OPENAI_API_KEY=... python3 scripts/eval_barriers.py

Mock numbers only show the plumbing works (keyword stand-in, labels written
alongside it). Labels are draft_unreviewed until a clinician reviews them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.domain.stage2 import BarrierCode  # noqa: E402
from app.providers.base import LLMProvider  # noqa: E402
from app.stage2.barrier import build_barrier_report, detect_red_flags  # noqa: E402
from app.stage2.config import load_barrier_config, load_red_flag_rules  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "barriers"
RED_FLAG = "RED_FLAG"
UNCLASSIFIED = "UNCLASSIFIED"
COLUMNS = [c.value for c in BarrierCode] + [RED_FLAG, UNCLASSIFIED]


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def evaluate_red_flags() -> dict[str, Any]:
    rules = load_red_flag_rules()
    data = _load("red_flags.json")
    missed = [
        rf["id"] for rf in data["red_flags"] if rf["expected_category"] not in detect_red_flags(rf["text"], rules)
    ]
    false_positives = [nr["id"] for nr in data["non_red_flags"] if detect_red_flags(nr["text"], rules)]
    return {
        "total": len(data["red_flags"]),
        "caught": len(data["red_flags"]) - len(missed),
        "missed": missed,
        "negatives": len(data["non_red_flags"]),
        "false_positives": false_positives,
    }


def evaluate_classification(llm_provider: LLMProvider) -> dict[str, Any]:
    rules, config = load_red_flag_rules(), load_barrier_config()
    matrix = {gold: {col: 0 for col in COLUMNS} for gold in COLUMNS[:-2]}
    low_confidence = 0
    errors = []
    for r in _load("responses.json")["responses"]:
        report = build_barrier_report(
            r["id"], "2026-W42", llm_provider=llm_provider, rules=rules, config=config, free_text=r["free_text"]
        )
        predicted = RED_FLAG if report.red_flag else (report.code.value if report.code else UNCLASSIFIED)
        matrix[r["expected_code"]][predicted] += 1
        low_confidence += int(report.follow_up_question is not None)
        if predicted != r["expected_code"]:
            errors.append({"id": r["id"], "expected": r["expected_code"], "predicted": predicted})
    total = sum(sum(row.values()) for row in matrix.values())
    correct = sum(matrix[c][c] for c in matrix)
    return {
        "matrix": matrix,
        "accuracy": round(correct / total, 3) if total else None,
        "per_code_recall": {c: round(matrix[c][c] / sum(matrix[c].values()), 3) for c in matrix},
        "follow_up_questions": low_confidence,
        "errors": errors,
        "total": total,
    }


def print_matrix(matrix: dict[str, dict[str, int]]) -> None:
    short = {RED_FLAG: "RF", UNCLASSIFIED: "?"}
    header = "gold\\pred " + " ".join(f"{short.get(c, c):>6}" for c in COLUMNS)
    print(header)
    for gold, row in matrix.items():
        print(f"{gold:9} " + " ".join(f"{row[c]:>6}" for c in COLUMNS))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, help="also write the result as JSON")
    args = parser.parse_args()

    from app.dependencies import get_llm_provider

    provider = get_llm_provider()
    red = evaluate_red_flags()
    cls = evaluate_classification(provider)
    print(f"provider: {type(provider).__name__}")
    print(f"\nred flags caught: {red['caught']}/{red['total']}  missed: {red['missed'] or '-'}")
    print(f"false positives on negatives: {len(red['false_positives'])}/{red['negatives']}  {red['false_positives'] or ''}")
    print(f"\nclassification accuracy: {cls['accuracy']} ({cls['total']} responses), follow-up asked: {cls['follow_up_questions']}\n")
    print_matrix(cls["matrix"])
    if cls["errors"]:
        print("\nmisclassified: " + ", ".join(f"{e['id']} {e['expected']}->{e['predicted']}" for e in cls["errors"]))
    if args.json:
        args.json.write_text(json.dumps({"red_flags": red, "classification": cls}, ensure_ascii=False, indent=2) + "\n")
    if red["missed"]:
        sys.exit(1)  # the 100% red flag gate


if __name__ == "__main__":
    main()

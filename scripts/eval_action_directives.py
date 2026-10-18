"""Evaluate action-directive extraction + normalization on tests/fixtures/visits/.

For each synthetic visit: structure_encounter (with segments) ->
normalize_directives -> compare to the labeled expected directives.

A prediction matches a label when their segment IDs overlap and, for the
"code" level, the catalog_code is equal. Reports precision/recall at two
levels -- detection (was a directive found there at all) and code (was it
mapped to the right catalog action) -- plus agreement accuracy on
code-matched pairs.

    python3 scripts/eval_action_directives.py            # mock provider
    ARIAD_MODE=provider OPENAI_API_KEY=... python3 scripts/eval_action_directives.py

Mock numbers only show the plumbing works: the mock is a keyword rule,
not a quality signal. Labels are draft_unreviewed until a clinician
reviews them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.pipeline.segments import ROLE_LABELS_KO  # noqa: E402
from app.pipeline.structure import structure_encounter  # noqa: E402
from app.providers.base import LLMProvider  # noqa: E402
from app.stage2.catalog import load_catalog  # noqa: E402
from app.stage2.normalizer import normalize_directives  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "visits"

Pred = dict[str, Any]  # segment_ids: set[str], catalog_code: str, agreement: str|None


def load_visits(fixtures_dir: Path = FIXTURES_DIR) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(fixtures_dir.glob("*.json"))]


def transcript_text_of(segments: list[dict[str, str]]) -> str:
    return "\n".join(f"{ROLE_LABELS_KO.get(s['role'], '화자')}: {s['text']}" for s in segments)


def predict_visit(visit: dict[str, Any], llm_provider: LLMProvider) -> list[Pred]:
    segments = visit["segments"]
    structure = structure_encounter(transcript_text_of(segments), llm_provider, segments=segments)
    items = normalize_directives(structure.action_directives, load_catalog(), f"P-{visit['visit_id']}-v1", llm_provider)
    by_directive = {d.directive_id: d for d in structure.action_directives}
    preds = []
    for item in items:
        d = by_directive[item.source_directive_id]
        preds.append(
            {
                "segment_ids": {s.segment_id for s in d.source_spans},
                "catalog_code": item.catalog_code,
                "agreement": d.patient_response.agreement.value if d.patient_response else None,
                "needs_review": item.needs_review,
            }
        )
    return preds


def _greedy_match(preds: list[Pred], expected: list[dict[str, Any]], use_code: bool) -> list[tuple[int, int]]:
    used: set[int] = set()
    pairs = []
    for ei, exp in enumerate(expected):
        for pi, pred in enumerate(preds):
            if pi in used or not (pred["segment_ids"] & set(exp["segment_ids"])):
                continue
            if use_code and pred["catalog_code"] != exp["catalog_code"]:
                continue
            used.add(pi)
            pairs.append((pi, ei))
            break
    return pairs


def score_visit(preds: list[Pred], expected: list[dict[str, Any]]) -> dict[str, int]:
    detect = _greedy_match(preds, expected, use_code=False)
    code = _greedy_match(preds, expected, use_code=True)
    agree = sum(1 for pi, ei in code if preds[pi]["agreement"] == expected[ei]["agreement"])
    return {
        "pred": len(preds),
        "gold": len(expected),
        "detect_tp": len(detect),
        "code_tp": len(code),
        "agreement_correct": agree,
        "needs_review": sum(1 for p in preds if p["needs_review"]),
    }


def _ratio(n: int, d: int) -> Optional[float]:
    return round(n / d, 3) if d else None


def summarize(rows: list[dict[str, int]]) -> dict[str, Any]:
    t = {k: sum(r[k] for r in rows) for k in rows[0]} if rows else {}
    return {
        **t,
        "detection_precision": _ratio(t.get("detect_tp", 0), t.get("pred", 0)),
        "detection_recall": _ratio(t.get("detect_tp", 0), t.get("gold", 0)),
        "code_precision": _ratio(t.get("code_tp", 0), t.get("pred", 0)),
        "code_recall": _ratio(t.get("code_tp", 0), t.get("gold", 0)),
        "agreement_accuracy": _ratio(t.get("agreement_correct", 0), t.get("code_tp", 0)),
    }


def evaluate(llm_provider: LLMProvider, fixtures_dir: Path = FIXTURES_DIR) -> dict[str, Any]:
    per_visit = {}
    for visit in load_visits(fixtures_dir):
        per_visit[visit["visit_id"]] = score_visit(predict_visit(visit, llm_provider), visit["expected_directives"])
    return {"per_visit": per_visit, "total": summarize(list(per_visit.values()))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, help="also write the result as JSON")
    args = parser.parse_args()

    from app.dependencies import get_llm_provider

    provider = get_llm_provider()
    result = evaluate(provider)
    print(f"provider: {type(provider).__name__}")
    print(f"{'visit':6} {'pred':>4} {'gold':>4} {'det':>4} {'code':>4} {'agree':>5}")
    for vid, r in result["per_visit"].items():
        print(f"{vid:6} {r['pred']:>4} {r['gold']:>4} {r['detect_tp']:>4} {r['code_tp']:>4} {r['agreement_correct']:>5}")
    t = result["total"]
    print(
        f"\ndetection P/R = {t['detection_precision']} / {t['detection_recall']}"
        f"\ncode      P/R = {t['code_precision']} / {t['code_recall']}"
        f"\nagreement acc = {t['agreement_accuracy']} (on {t['code_tp']} code-matched)"
        f"\nneeds_review  = {t['needs_review']} / {t['pred']} predicted items"
    )
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

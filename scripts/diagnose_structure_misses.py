#!/usr/bin/env python3
"""`make diagnose-structure GOLD=tests/evals/gold/x.gold.json OUTPUTS="data/.../x.openai_gpt-4o.run*.output.json"`

tasks/13-d: for each conversation item an eval run missed, says whether the
summary paraphrased it (some keyword groups in one item), split it across
items, or left it out -- from the already-saved eval outputs, no API call.

It also re-scores each saved output with the current scorer (recall and
leaks), so a scorer fix can be checked without paying for new runs.

Prints only gold keywords (already in the repo) and section names, never
output or transcript text, so it is safe on real recordings.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import use_case_defaults  # noqa: E402
from env_paths import require_files  # noqa: E402

from app.eval.structure_eval import diagnose_miss, score_structure  # noqa: E402

USAGE = ('GOLD=x.gold.json OUTPUTS="x.*.run*.output.json" python3 scripts/diagnose_structure_misses.py'
         '  (or CASE=er_3023432)')


def main() -> int:
    if os.environ.get("CASE"):  # tasks/16
        error = use_case_defaults(os.environ["CASE"])
        if error:
            print(error)
            return 1
    paths = require_files(["GOLD"], USAGE)
    if paths is None:
        return 1
    gold = json.loads(paths[0].read_text(encoding="utf-8"))
    outputs = sorted(glob.glob(os.environ.get("OUTPUTS", "")))
    if not outputs:
        print(f"OUTPUTS={os.environ.get('OUTPUTS', '')!r}: no files match.\nUsage: {USAGE}")
        return 1

    items = {item["id"]: item for item in gold["items"] if item["tier"] == "conversation"}
    kinds: dict[str, list[str]] = {}
    summaries = []
    print(f"{'item':<32}{'run':<6}{'kind':<9}{'quote':<7}{'best section':<28}keyword groups")
    print("-" * 110)
    for path in outputs:
        output = json.loads(Path(path).read_text(encoding="utf-8"))
        run = Path(path).name.split(".")[-3]  # x.provider.runK.output.json -> runK
        score = score_structure(output, gold, "")
        summaries.append((run, score))
        for result in score.items:
            if result.id not in items or result.hit:
                continue
            item = items[result.id]
            d = diagnose_miss(output, item)
            kinds.setdefault(d.kind, []).append(d.id)
            groups = "  ".join(("✓" if i in d.best_groups else "✗") + "[" + "|".join(g) + "]"
                               for i, g in enumerate(item["must_match"]))
            print(f"{d.id:<32}{run:<6}{d.kind:<9}{'yes' if d.in_quote else '-':<7}{d.best_section or '-':<28}{groups}")
    print()
    for kind, explain in (("partial", "some groups in one item: paraphrased or part dropped"),
                          ("split", "all groups, but across items"),
                          ("omitted", "no group in any summary item")):
        print(f"{kind:<8} {len(kinds.get(kind, [])):>3}  {explain}")
    print("quote=yes: the whole item is in a term-candidate quote, so it was said but not summarised.")
    print("\nre-scored with the current scorer (frame-term recall needs FRAMES -- see make eval-structure):")
    for run, score in summaries:
        recall = "-" if score.conversation_recall is None else f"{score.conversation_recall:.0%}"
        print(f"  {run}: conversation recall {recall}  |  context_only leaks {score.context_only_leaks or 0}"
              f"  |  must_exclude leaks {score.excluded_leaks or 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

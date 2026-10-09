#!/usr/bin/env python3
"""`TRANSCRIPT=data/annotations/sim_icu_01.transcript.json GOLD=data/annotations/sim_icu_01.gold.json make eval-structure [REAL=1]`

tasks/09_STRUCTURE_EVAL_AGAINST_CLINICIAN_GOLD.md: feeds a transcript
through the app's own clinical_enrichment + structure_transcript stages and
scores the result against a clinician gold list (app/eval/structure_eval.py):

  conversation recall  share of things said in the encounter that the
                       summary kept
  context_only leaks   chart-only facts (drug/test names never said aloud)
                       that appeared anyway -- must be 0 (CLAUDE.md)
  gold check           the gold itself against the input text, so a wrong
                       gold keyword is caught before it is blamed on the LLM
  latency              per stage, for the "summary right after the encounter"
                       target

TRANSCRIPT is any {"segments": [...]} file: the clinician answer
(answer_to_transcript.py) = "oracle ASR", measuring structuring alone; a
real ASR run's segments = end to end. Segments without timestamps get
pseudo-times (index order) -- only their order matters to these stages.

Default is the mock LLM, which echoes transcript lines: its recall only
shows the gold keywords are reachable, it is not a quality score. REAL=1
(--real) uses OPENAI_API_KEY after a y/N prompt (costs money). Output JSON
goes next to the gold (data/, gitignored). Prints item ids and section
names only, never transcript text.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_asr_engines import _load_env_local  # noqa: E402
from eval_clinical_enrichment import _build_provider  # noqa: E402

from app.domain.models import DiarizedSegment  # noqa: E402
from app.eval.structure_eval import score_structure  # noqa: E402
from app.pipeline.enrichment import enrich_clinical_findings  # noqa: E402
from app.pipeline.structure import structure_encounter  # noqa: E402
from app.routes.encounters import _ROLE_LABELS_KO  # noqa: E402


def load_segments(path: Path) -> list[DiarizedSegment]:
    raw = json.loads(path.read_text(encoding="utf-8"))["segments"]
    return [
        DiarizedSegment(
            id=seg.get("id", f"seg_{i + 1:03d}"),
            speaker=seg["speaker"],
            role=seg.get("expected_role", seg.get("role", "unknown")),
            start=float(seg.get("start", i)),
            end=float(seg.get("end", i + 1)),
            text=seg["text"],
        )
        for i, seg in enumerate(raw)
    ]


def transcript_text(segments: list[DiarizedSegment]) -> str:
    """Same "역할: 문장" lines the app builds (routes/encounters.py)."""
    return "\n".join(f"{_ROLE_LABELS_KO.get(s.role, '화자')}: {s.text}" for s in segments)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="use OPENAI_API_KEY instead of the mock provider")
    args = parser.parse_args()

    transcript_path = Path(os.environ.get("TRANSCRIPT", ""))
    gold_path = Path(os.environ.get("GOLD", ""))
    if not transcript_path.is_file() or not gold_path.is_file():
        print("Usage: TRANSCRIPT=x.transcript.json GOLD=x.gold.json python3 scripts/eval_structure_against_gold.py")
        return 1
    _load_env_local()
    provider, label = _build_provider(args.real or os.environ.get("REAL") == "1")

    segments = load_segments(transcript_path)
    text = transcript_text(segments)
    gold = json.loads(gold_path.read_text(encoding="utf-8"))

    start = time.perf_counter()
    enrichment = enrich_clinical_findings(segments, provider)
    enrichment_s = time.perf_counter() - start
    start = time.perf_counter()
    structure = structure_encounter(text, provider)
    structure_s = time.perf_counter() - start

    output = {"enrichment": enrichment.model_dump(), "structure": structure.model_dump()}
    out_path = gold_path.with_name(f"{gold.get('case', gold_path.stem)}.{label.replace(':', '_')}.output.json")
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    score = score_structure(output, gold, text)

    print(f"\ncase={gold.get('case')} provider={label} segments={len(segments)}")
    print(f"{'item':<32}{'tier':<14}{'result':<8}sections")
    print("-" * 78)
    for item in score.items:
        expected_absent = item.tier == "context_only"
        if expected_absent:
            result = "LEAK" if item.hit else "absent"
        else:
            result = "HIT" if item.hit else "miss"
        print(f"{item.id:<32}{item.tier:<14}{result:<8}{', '.join(item.sections)}")
    print()
    recall = "-" if score.conversation_recall is None else f"{100 * score.conversation_recall:.0f}%"
    print(f"conversation recall: {recall}  |  context_only leaks: {len(score.context_only_leaks)}  |  "
          f"enrichment validator violations: {len(enrichment.validator_violations)}")
    print(f"latency: enrichment {enrichment_s:.1f}s + structure {structure_s:.1f}s = {enrichment_s + structure_s:.1f}s")
    if score.gold_errors:
        print("gold check FAILED (fix the gold before reading the scores):")
        for error in score.gold_errors:
            print(f"  {error}")
    if label == "mock":
        print("note: mock echoes transcript lines -- recall here only proves the gold is reachable.")
    print(f"output -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

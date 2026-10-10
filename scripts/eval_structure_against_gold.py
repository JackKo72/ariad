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
Background segments (role "background", the answer's "noise:" lines) are
dropped by default, as a clinician would mark them 배경 at role
confirmation; INCLUDE_BACKGROUND=1 feeds them too, to test whether the LLM
pulls other people's talk into the summary.

FRAMES=stroke (or seizure, comma-separated) scores as if the clinician had
picked that clinical frame: its frame_term items become expected instead
of leaks, AND passes that frame to the structure stage (tasks/10) -- a single
frame; the first one listed is sent.
REPEAT=3 runs the same input 3 times (LLM output varies run to run): per-item
hit counts (e.g. "HIT 2/3"), recall as mean (min-max), outputs saved as
<case>.<provider>.runK.output.json.
Gold items with a "note" are printed as a clinician review checklist:
keyword matching cannot judge polarity ("clopi loading 안 함").

Default is the mock LLM, which echoes transcript lines: its recall only
shows the gold keywords are reachable, it is not a quality score. REAL=1
(--real) uses OPENAI_API_KEY after a y/N prompt (costs money). Output JSON
goes next to the TRANSCRIPT (data/, gitignored). Prints item ids and section
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
from env_paths import require_files  # noqa: E402
from eval_clinical_enrichment import _build_provider  # noqa: E402

from app.domain.models import DiarizedSegment  # noqa: E402
from app.eval.structure_eval import score_structure  # noqa: E402
from app.observability import StageTimer  # noqa: E402
from app.pipeline.enrichment import enrich_clinical_findings  # noqa: E402
from app.pipeline.review_checklist import build_review_checklist  # noqa: E402
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

    paths = require_files(["TRANSCRIPT", "GOLD"],
                          "TRANSCRIPT=x.transcript.json GOLD=x.gold.json python3 scripts/eval_structure_against_gold.py")
    if paths is None:
        return 1
    transcript_path, gold_path = paths
    _load_env_local()
    provider, label = _build_provider(args.real or os.environ.get("REAL") == "1")

    segments = load_segments(transcript_path)
    if os.environ.get("INCLUDE_BACKGROUND") != "1":
        segments = [s for s in segments if s.role != "background"]
    text = transcript_text(segments)
    gold = json.loads(gold_path.read_text(encoding="utf-8"))

    frames = frozenset(f.strip() for f in os.environ.get("FRAMES", "").split(",") if f.strip())
    pipeline_frame = os.environ.get("FRAMES", "").split(",")[0].strip() or None
    repeat = max(1, int(os.environ.get("REPEAT", "1")))
    case = gold.get("case", gold_path.stem)
    runs = []
    for k in range(1, repeat + 1):
        timer = StageTimer()  # the real provider records token usage per call
        start = time.perf_counter()
        enrichment = enrich_clinical_findings(segments, provider, stage_timer=timer)
        enrichment_s = time.perf_counter() - start
        start = time.perf_counter()
        structure = structure_encounter(text, provider, stage_timer=timer, clinical_frame=pipeline_frame)
        structure_s = time.perf_counter() - start
        tokens_in = sum(r.input_tokens or 0 for r in timer.records)
        tokens_out = sum(r.output_tokens or 0 for r in timer.records)
        output = {"enrichment": enrichment.model_dump(), "structure": structure.model_dump()}
        # Next to the TRANSCRIPT (gitignored data/), never next to the gold --
        # gold lives in the repo (tests/evals/gold/) and outputs quote transcript text.
        suffix = f".run{k}" if repeat > 1 else ""
        out_path = transcript_path.with_name(f"{case}.{label.replace(':', '_')}{suffix}.output.json")
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        runs.append({"score": score_structure(output, gold, text, frames=frames), "structure": structure,
                     "violations": len(enrichment.validator_violations), "enrichment_s": enrichment_s,
                     "structure_s": structure_s, "out_path": out_path,
                     "tokens_in": tokens_in, "tokens_out": tokens_out})

    def spread(values: list[float], fmt: str) -> str:
        if not values:
            return "-"
        mean = fmt.format(sum(values) / len(values))
        return mean if len(values) == 1 else f"{mean} ({fmt.format(min(values))}-{fmt.format(max(values))})"

    frame_of = {item["id"]: item.get("frame") for item in gold["items"]}
    print(f"\ncase={case} provider={label} segments={len(segments)} frames={sorted(frames) or '-'} runs={repeat}")
    print(f"{'item':<34}{'tier':<14}{'result':<10}sections")
    print("-" * 80)
    for i, item in enumerate(runs[0]["score"].items):
        hits = sum(run["score"].items[i].hit for run in runs)
        sections = sorted({sec for run in runs for sec in run["score"].items[i].sections})
        expected_absent = item.tier in ("context_only", "must_exclude") or (
            item.tier == "frame_term" and frame_of[item.id] not in frames)
        word = ("LEAK" if hits else "absent") if expected_absent else ("HIT" if hits else "miss")
        result = word if repeat == 1 else f"{word} {hits}/{repeat}"
        print(f"{item.id:<34}{item.tier:<14}{result:<10}{', '.join(sections)}")
    print()
    pct = "{:.0%}"
    conv = [r["score"].conversation_recall for r in runs if r["score"].conversation_recall is not None]
    frame_r = [r["score"].frame_recall for r in runs if r["score"].frame_recall is not None]
    print(f"conversation recall: {spread(conv, pct)}  |  "
          f"context_only leaks: {sum(len(r['score'].context_only_leaks) for r in runs)}  |  "
          f"must_exclude leaks: {sum(len(r['score'].excluded_leaks) for r in runs)}  |  "
          f"enrichment validator violations: {sum(r['violations'] for r in runs)}  (leak/violation counts summed over runs)")
    print(f"frame-term recall: {spread(frame_r, pct)}  |  frame-term leaks: {sum(len(r['score'].frame_leaks) for r in runs)}")
    slots = ("treatments_given", "decisions", "consents", "disposition", "prognosis_and_goals",
             "family_statements", "term_candidates")
    print("tasks/10 slots filled: " + ", ".join(
        f"{k} {spread([float(len(getattr(r['structure'], k))) for r in runs], '{:.1f}' if repeat > 1 else '{:.0f}')}"
        for k in slots)
        + "  |  term_candidates inference/exam: "
        + spread([float(sum(c.risk == "inference" for c in r["structure"].term_candidates)) for r in runs],
                 "{:.1f}" if repeat > 1 else "{:.0f}")
        + "/" + spread([float(sum(c.risk == "exam" for c in r["structure"].term_candidates)) for r in runs],
                       "{:.1f}" if repeat > 1 else "{:.0f}")
        + "  |  review checklist items: "
        + spread([float(len(build_review_checklist(r["structure"]))) for r in runs], "{:.1f}" if repeat > 1 else "{:.0f}"))
    enrichment_s = sum(r["enrichment_s"] for r in runs) / repeat
    structure_s = sum(r["structure_s"] for r in runs) / repeat
    tokens_in = sum(r["tokens_in"] for r in runs) / repeat
    tokens_out = sum(r["tokens_out"] for r in runs) / repeat
    score = runs[-1]["score"]
    out_path = runs[-1]["out_path"]
    notes = [item for item in gold["items"] if item.get("note")]
    if notes:
        print("clinician review checklist (read these in the output JSON):")
        for item in notes:
            print(f"  [ ] {item['id']}: {item['note']}")
    print(f"latency{' (mean)' if repeat > 1 else ''}: enrichment {enrichment_s:.1f}s + structure {structure_s:.1f}s = {enrichment_s + structure_s:.1f}s")
    if tokens_in or tokens_out:
        print(f"tokens per encounter{' (mean)' if repeat > 1 else ''}: input {tokens_in:,.0f} + output {tokens_out:,.0f} "
              "(enrichment + structure; multiply by your provider's current per-token price for cost)")
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

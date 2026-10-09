#!/usr/bin/env python3
"""`SET_DIR=data/eval_noisy_diarization ENGINES=sherpa_cpu make eval-diarization-der`

tasks/07_NOISY_DIARIZATION_EVAL.md: scores every condition of the set made
by scripts/generate_noisy_diarization_set.py with every requested
diarization engine and preprocessing mode, against the known reference:

  DER (missed / false alarm / confusion), speakers ref vs hyp, RTF, and
  bg_leak -- the share of the neighbouring conversation's speech that landed
  under OUR doctor's/patient's label (app/eval/diarization_metrics.py).

Engines are the CANDIDATES of scripts/compare_diarization_engines.py
(sherpa_cpu, pyannote_cuda, sortformer_cuda, ...) -- same cold/warm
measurement, same skip-with-reason when a package/GPU/token is missing.
PREPROCESS=none,light_denoise runs app.audio.preprocess.standardize_audio
first, so the app's own denoise setting is A/B'd on the same ground truth.

Env: SET_DIR (default data/eval_noisy_diarization), ENGINES (default
sherpa_cpu), PREPROCESS (default none,light_denoise), COLLAR (default 0.25 s).
Writes <SET_DIR>/der_results.json. Prints only scores and counts -- never a
speaker label or transcript text. Opt-in, free, never part of `make test`.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.audio.preprocess import standardize_audio  # noqa: E402
from app.eval.diarization_metrics import SpeakerSegment, score_diarization  # noqa: E402
from compare_diarization_engines import CANDIDATES, _load_env_local  # noqa: E402


def load_reference(path: Path) -> list[SpeakerSegment]:
    return [SpeakerSegment(**seg) for seg in json.loads(path.read_text(encoding="utf-8"))["segments"]]


def score_row(condition: dict, engine: str, preprocess: str, result: dict, reference: list[SpeakerSegment],
              collar: float) -> dict:
    row = {"condition": condition["name"], "noise": condition["noise"], "snr_db": condition["snr_db"],
           "engine": engine, "preprocess": preprocess}
    if result.get("skipped"):
        return {**row, "skipped": True, "reason": result["reason"]}
    hypothesis = [SpeakerSegment(float(s), float(e), str(label)) for s, e, label in result["segments"]]
    score = score_diarization(reference, hypothesis, collar=collar)
    return {
        **row,
        "skipped": False,
        "der": round(score.der, 4),
        "missed_s": round(score.missed_seconds, 2),
        "false_alarm_s": round(score.false_alarm_seconds, 2),
        "confusion_s": round(score.confusion_seconds, 2),
        "reference_s": round(score.reference_seconds, 2),
        "background_leakage": None if score.background_leakage is None else round(score.background_leakage, 4),
        "speakers_ref": score.reference_speakers,
        "speakers_hyp": score.hypothesis_speakers,
        "rtf": result.get("rtf"),
    }


def print_table(rows: list[dict]) -> None:
    header = (f"{'condition':<20}{'engine':<20}{'prep':<15}{'DER%':>7}{'miss%':>7}{'FA%':>7}"
              f"{'conf%':>7}{'bg_leak%':>9}{'spk r/h':>9}{'RTF':>7}")
    print(header)
    print("-" * len(header))
    for r in rows:
        lead = f"{r['condition']:<20}{r['engine']:<20}{r['preprocess']:<15}"
        if r["skipped"]:
            print(f"{lead}SKIPPED")
            continue
        total = r["reference_s"] or 1.0
        leak = "-" if r["background_leakage"] is None else f"{100 * r['background_leakage']:.1f}"
        rtf = "-" if r["rtf"] is None else f"{r['rtf']:.3f}"
        print(f"{lead}{100 * r['der']:>7.1f}{100 * r['missed_s'] / total:>7.1f}"
              f"{100 * r['false_alarm_s'] / total:>7.1f}{100 * r['confusion_s'] / total:>7.1f}"
              f"{leak:>9}{r['speakers_ref']:>4}/{r['speakers_hyp']:<4}{rtf:>7}")


def main() -> int:
    set_dir = Path(os.environ.get("SET_DIR", REPO_ROOT / "data" / "eval_noisy_diarization"))
    manifest_path = set_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path} -- run `make noisy-diarization-set` first.")
        return 1
    engines = [e.strip() for e in os.environ.get("ENGINES", "sherpa_cpu").split(",")]
    unknown = [e for e in engines if e not in CANDIDATES]
    if unknown:
        print(f"Unknown engine(s) {unknown}. Available: {', '.join(CANDIDATES)}")
        return 1
    preprocess_modes = [m.strip() for m in os.environ.get("PREPROCESS", "none,light_denoise").split(",")]
    collar = float(os.environ.get("COLLAR", "0.25"))
    _load_env_local()

    conditions = json.loads(manifest_path.read_text(encoding="utf-8"))["conditions"]
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for condition in conditions:
            reference = load_reference(set_dir / condition["ref"])
            for mode in preprocess_modes:
                wav_path = Path(tmp) / f"{condition['name']}.{mode}.wav"
                standardize_audio(set_dir / condition["wav"], wav_path, mode)
                for engine in engines:
                    print(f"[{condition['name']} / {engine} / {mode}] running ...", flush=True)
                    row = score_row(condition, engine, mode, CANDIDATES[engine](wav_path), reference, collar)
                    if row["skipped"]:
                        print(f"  SKIPPED: {row['reason']}")
                    rows.append(row)

    print()
    print(f"collar={collar}s; % columns are shares of reference speech time; "
          "bg_leak% = neighbour speech labelled as one of OUR speakers (lower is safer)")
    print_table(rows)
    out_path = set_dir / "der_results.json"
    out_path.write_text(json.dumps({"collar": collar, "rows": rows}, indent=2), encoding="utf-8")
    print(f"\nresults -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""`apps/api/.venv/bin/python scripts/compare_asr_accuracy.py [--ko-modes auto_then_ko,ko_only]`

tasks/03_SPEAKER_MERGE_AND_LATENCY.md follow-up, item 4: speed alone (RTF)
must not decide the default ASR path -- this compares *accuracy* across
ko_mode candidates on the one Korean clinical-conversation fixture that
already carries hand-authored ground truth covering exactly the categories
the task asks for: medication name, dose, a negation ("아스피린 미투여"),
a relative date, and per-speaker role. See
tests/fixtures/audio/sample_consultation.transcript.json.

For each requested ko_mode this runs the real local ASR provider once
(cold, to warm its model cache -- same as scripts/diagnose_asr_stages.py)
and reports:

  - RTF (inference_ms / audio duration), reusing the same diagnostics dict
    scripts/diagnose_asr_stages.py uses, so speed and accuracy are visible
    in the same run.
  - Speaker/diarization consistency: gt segments are matched to predicted
    segments by time overlap, predicted labels (A/B/C) are mapped to gt
    speakers (A/B) by majority overlap, then compared -- this measures
    diarization correctness (role assignment itself is a clinician step
    after ASR, per DiarizedSegment's docstring, not something ASR decides).
  - Clinical-anchor keyword checks: does the matched predicted text contain
    the medication name, the dose, a negation marker, and the date phrase
    from the ground truth (see ACCURACY_CHECKS below)? This is a coarse
    presence check, not exact-match scoring -- ASR spacing/tokenization
    varies even when the content is correct.
  - tasks/06_ASR_OUTPUT_VERIFICATION.md: per-segment CER/WER (app.eval.
    asr_metrics) printed for manual review, plus a whole-transcript CER/WER
    (all gt segments concatenated vs. all actual predicted segments
    concatenated) as the number to trust -- a real run surfaced that this
    fixture's diarization merges every speaker turn into fewer segments
    than ground truth has, so every short gt segment ends up compared
    against the same large merged blob; per-segment CER/WER in that case
    is not meaningful (a WARNING is printed when segment counts don't
    match). CER is primary (docs/TESTING_AND_EVALS.md), WER is secondary/
    informational for Korean.
  - The same whole-transcript CER/WER recomputed after running both sides
    through app.pipeline.asr_normalize's Sino-Korean number-word
    normalizer, to show whether that candidate post-ASR stage actually
    reduces meaning-preserving mismatches (e.g. "오"/"5") rather than just
    moving the fixture's own spoken-form ground truth further away from a
    digit-normalized prediction, or vice versa.
  - app.pipeline.medication_candidates.find_medication_candidates() run
    against each predicted segment -- dictionary-fuzzy-match medication
    name candidates, printed as needs_review suggestions. Never mutates
    the predicted text; this is visibility into what the candidate (not
    yet wired into any provider) would flag, not a correction being applied.
  - Full expected-vs-predicted text per segment, for manual review of
    anything the automated checks don't catch (wrong numbers, dropped
    words, hallucinated content).

Synthetic fixture only (CLAUDE.md: no real patient audio/transcripts in
tests). Prints fixture transcript text to stdout by design (that's the
point of an accuracy check) -- this is committed, synthetic fixture
content already in the repo, not live application/patient data, so it does
not touch the "no transcript in general application logs" rule.

Opt-in, free (local ASR only, no OpenAI call). Never part of `make
test`/`make e2e`.
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

DEFAULT_AUDIO = REPO_ROOT / "tests" / "fixtures" / "audio" / "sample_consultation.wav"
DEFAULT_GROUND_TRUTH = REPO_ROOT / "tests" / "fixtures" / "audio" / "sample_consultation.transcript.json"

# Anchor checks keyed by ground-truth segment id (see DEFAULT_GROUND_TRUTH).
# Keywords are space-stripped before matching, since ASR word-spacing can
# differ from the ground truth even when the content is right.
ACCURACY_CHECKS = [
    {"segment_id": "seg_003", "label": "medication name (리시노프릴)", "keywords": ["리시노프릴"]},
    {"segment_id": "seg_003", "label": "dose (5mg)", "keywords": ["오밀리그램", "5밀리그램", "5mg"]},
    {
        "segment_id": "seg_005",
        "label": "negation (아스피린 미투여)",
        "keywords": ["않습니다", "않는", "않아"],
    },
    {"segment_id": "seg_007", "label": "date (시월 첫째 주)", "keywords": ["시월"]},
]


def _normalize(text: str) -> str:
    return text.replace(" ", "")


def _load_ground_truth(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["segments"]


def _overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _match_predicted_text(gt_segment: dict, predicted_segments: list) -> tuple[str, str | None]:
    """Concatenate predicted-segment text overlapping `gt_segment`, and
    return (matched_text, dominant_predicted_speaker_label)."""
    overlaps: list[tuple[float, object]] = []
    for seg in predicted_segments:
        ov = _overlap_seconds(gt_segment["start"], gt_segment["end"], seg.start, seg.end)
        if ov > 0:
            overlaps.append((ov, seg))
    if not overlaps:
        return "", None
    overlaps.sort(key=lambda pair: pair[0], reverse=True)
    matched_text = " ".join(seg.text for _, seg in sorted(overlaps, key=lambda pair: pair[1].start))
    dominant_speaker = overlaps[0][1].speaker
    return matched_text, dominant_speaker


def _speaker_mapping_accuracy(gt_segments: list[dict], predicted_segments: list) -> tuple[float, int, int]:
    """Map each predicted speaker label to the gt speaker it overlaps with
    the most (by total overlap seconds), then count how many gt segments
    agree with that mapping. Returns (accuracy, correct, total)."""
    overlap_totals: dict[str, dict[str, float]] = {}
    per_segment_pred_speaker: list[str | None] = []
    for gt_seg in gt_segments:
        best_ov = 0.0
        best_speaker = None
        for seg in predicted_segments:
            ov = _overlap_seconds(gt_seg["start"], gt_seg["end"], seg.start, seg.end)
            if ov > best_ov:
                best_ov = ov
                best_speaker = seg.speaker
            if ov > 0:
                overlap_totals.setdefault(seg.speaker, {}).setdefault(gt_seg["speaker"], 0.0)
                overlap_totals[seg.speaker][gt_seg["speaker"]] += ov
        per_segment_pred_speaker.append(best_speaker)

    label_map = {
        pred_speaker: max(gt_counts, key=gt_counts.get) for pred_speaker, gt_counts in overlap_totals.items()
    }

    correct = 0
    for gt_seg, pred_speaker in zip(gt_segments, per_segment_pred_speaker):
        mapped = label_map.get(pred_speaker) if pred_speaker is not None else None
        if mapped == gt_seg["speaker"]:
            correct += 1
    total = len(gt_segments)
    return (correct / total if total else float("nan"), correct, total)


def _run_one_mode(ko_mode: str, audio_path: Path, ground_truth: list[dict]) -> None:
    from app.domain.errors import AriadError
    from app.domain.models import AudioAsset
    from app.eval.asr_metrics import compute_cer, compute_wer
    from app.pipeline.asr_normalize import normalize_korean_number_words
    from app.pipeline.medication_candidates import find_medication_candidates
    from app.providers.sherpa_onnx_asr import SherpaOnnxASRProvider, models_available

    models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
    if not models_available(models_dir):
        print(f"sherpa-onnx model files not found under {models_dir!r}. See README.md.")
        return

    fake_asset = AudioAsset(
        id="accuracy-check",
        encounter_id="accuracy-check",
        kind="original",
        size_bytes=audio_path.stat().st_size,
        duration_seconds=0.0,
        created_at="1970-01-01T00:00:00+00:00",
    )

    provider = SherpaOnnxASRProvider(models_dir=models_dir, ko_mode=ko_mode)

    print(f"\n{'=' * 72}\nko_mode={ko_mode}\n{'=' * 72}")
    diagnostics: dict = {}
    try:
        predicted_segments = provider.transcribe(fake_asset, str(audio_path), diagnostics=diagnostics)
    except AriadError as exc:
        print(f"transcribe() failed: [{exc.code}] {exc.message}")
        return

    audio_duration = diagnostics.get("audio_duration_seconds", 0.0)
    inference_ms = (
        diagnostics.get("diarize_ms", 0.0)
        + diagnostics.get("auto_total_ms", 0.0)
        + diagnostics.get("ko_total_ms", 0.0)
    )
    rtf = (inference_ms / 1000) / audio_duration if audio_duration else float("nan")
    print(f"RTF: {rtf:.2f}x  (audio_duration={audio_duration:.2f}s, inference_ms={inference_ms:.1f})")

    accuracy, correct, total = _speaker_mapping_accuracy(ground_truth, predicted_segments)
    print(f"speaker/diarization consistency: {correct}/{total} segments ({accuracy * 100:.0f}%)")

    if len(predicted_segments) < len(ground_truth):
        print(
            f"\nWARNING: predicted segment count ({len(predicted_segments)}) < ground truth segment "
            f"count ({len(ground_truth)}) -- diarization likely merged multiple speaker turns into "
            "fewer segments than the script expected (known limitation, see README.md's "
            "\"화자분리가 ... 구분하지 못함\" note). Every short gt segment below will then overlap "
            "the SAME large merged predicted segment and print identical text -- per-segment CER/WER "
            "in that case compares a short reference against the whole merged blob and is NOT "
            "meaningful (expect CER/WER > 1.0). Use the whole-transcript CER/WER printed below "
            "instead; it does not depend on segment-count matching."
        )

    matched_by_id = {}
    print("\nPer-segment expected vs. predicted text:")
    for gt_seg in ground_truth:
        matched_text, pred_speaker = _match_predicted_text(gt_seg, predicted_segments)
        matched_by_id[gt_seg["id"]] = matched_text
        cer = compute_cer(gt_seg["text"], matched_text)
        wer = compute_wer(gt_seg["text"], matched_text)
        print(f"  [{gt_seg['id']}] gt_speaker={gt_seg['speaker']} pred_speaker={pred_speaker}")
        print(f"    expected : {gt_seg['text']}")
        print(f"    predicted: {matched_text or '(no overlapping predicted segment)'}")
        print(f"    CER={cer.rate:.3f} (S={cer.substitutions} D={cer.deletions} I={cer.insertions} / {cer.ref_length} chars)"
              f"  WER={wer.rate:.3f} (S={wer.substitutions} D={wer.deletions} I={wer.insertions} / {wer.ref_length} words)"
              + ("  (not meaningful -- see WARNING above)" if len(predicted_segments) < len(ground_truth) else ""))

    # tasks/06 real-data finding (2026-10-07): the per-gt-segment CER/WER
    # above is only meaningful when predicted segments roughly correspond
    # 1:1 to gt segments. When diarization merges everything into fewer
    # segments than that (reproducible on this fixture, see warning above),
    # every gt segment redundantly compares against the same large blob.
    # This whole-transcript comparison -- one reference string (all gt
    # segments concatenated in order) against one hypothesis string (all
    # *actual* predicted segments concatenated in order, deduplicated by
    # construction since it iterates predicted_segments directly, not the
    # gt-segment loop above) -- is correct regardless of how many segments
    # either side has, so it is the number to trust.
    whole_gt_text = " ".join(seg["text"] for seg in ground_truth)
    whole_predicted_text = " ".join(seg.text for seg in sorted(predicted_segments, key=lambda s: s.start))
    whole_cer = compute_cer(whole_gt_text, whole_predicted_text)
    whole_wer = compute_wer(whole_gt_text, whole_predicted_text)
    print(
        f"\ntasks/06 verification stage -- whole-transcript CER: {whole_cer.rate:.3f} "
        f"({whole_cer.substitutions + whole_cer.deletions + whole_cer.insertions}/{whole_cer.ref_length} chars), "
        f"whole-transcript WER: {whole_wer.rate:.3f} "
        f"({whole_wer.substitutions + whole_wer.deletions + whole_wer.insertions}/{whole_wer.ref_length} words)  "
        "<- primary number, diarization-segment-count-independent"
    )

    normalized_cer = compute_cer(normalize_korean_number_words(whole_gt_text), normalize_korean_number_words(whole_predicted_text))
    normalized_wer = compute_wer(normalize_korean_number_words(whole_gt_text), normalize_korean_number_words(whole_predicted_text))
    print(
        f"after normalize_korean_number_words() on both sides -- CER: {normalized_cer.rate:.3f}, "
        f"WER: {normalized_wer.rate:.3f}  "
        f"(delta CER {normalized_cer.rate - whole_cer.rate:+.3f}, delta WER {normalized_wer.rate - whole_wer.rate:+.3f})"
    )

    print("\nMedication name candidates (needs_review -- never auto-applied):")
    any_candidate = False
    for gt_seg in ground_truth:
        predicted_text = matched_by_id.get(gt_seg["id"], "")
        for candidate in find_medication_candidates(predicted_text):
            any_candidate = True
            print(
                f"  [{gt_seg['id']}] '{candidate.matched_span}' -> suggest '{candidate.suggested_name}' "
                f"(similarity={candidate.similarity:.2f})"
            )
    if not any_candidate:
        print("  (no candidates above the similarity threshold)")

    gt_segment_ids = {seg["id"] for seg in ground_truth}
    print("\nClinical-anchor checks:")
    for check in ACCURACY_CHECKS:
        if check["segment_id"] not in gt_segment_ids:
            # This ground truth file (e.g. a different fixture passed via
            # GROUND_TRUTH=) doesn't have this segment id at all -- say so
            # plainly instead of printing a misleading FAIL for a check
            # that was never applicable here.
            print(f"  [SKIPPED] {check['segment_id']}: {check['label']} (not in this ground truth file)")
            continue
        text = _normalize(matched_by_id.get(check["segment_id"], ""))
        passed = any(_normalize(kw) in text for kw in check["keywords"])
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check['segment_id']}: {check['label']}")


def main() -> int:
    audio_path = Path(os.environ.get("AUDIO", str(DEFAULT_AUDIO)))
    ground_truth_path = Path(os.environ.get("GROUND_TRUTH", str(DEFAULT_GROUND_TRUTH)))
    ko_modes_arg = os.environ.get("KO_MODES", "auto_then_ko,ko_only")
    ko_modes = [m.strip() for m in ko_modes_arg.split(",") if m.strip()]

    if not audio_path.exists():
        print(f"File not found: {audio_path}")
        return 1
    if not ground_truth_path.exists():
        print(f"Ground truth file not found: {ground_truth_path}")
        return 1

    ground_truth = _load_ground_truth(ground_truth_path)

    print(f"audio: {audio_path}")
    print(f"ground truth: {ground_truth_path} ({len(ground_truth)} segments)")
    print(f"comparing ko_modes: {ko_modes}")

    for ko_mode in ko_modes:
        _run_one_mode(ko_mode, audio_path, ground_truth)

    print(
        "\nNote: this compares candidates against the existing default "
        "(auto_then_ko) on synthetic fixture data only. Promote a candidate "
        "to the default path only once it matches or beats the baseline on "
        "both RTF and every accuracy check above -- do not decide from RTF "
        "alone (see tasks/03_SPEAKER_MERGE_AND_LATENCY.md item 4)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

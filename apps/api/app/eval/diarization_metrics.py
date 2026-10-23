"""Diarization accuracy scoring (docs/TESTING_AND_EVALS.md "Diarization: DER,
speaker confusion, overlap recall" -- listed there as the metric, but no code
computed it until now; scripts/compare_diarization_engines.py only measured
speed/RTF and a raw turn *count*, which says nothing about correctness and
actually goes *up* with over-segmentation, tasks/03's known failure mode).

Standard frame-based DER (the same definition NIST / pyannote.metrics use):

    DER = (missed + false_alarm + confusion) / total reference speech

counted per frame, with overlapping speech counted once per speaker, and an
optimal one-to-one mapping between reference and hypothesis speaker labels
(hypothesis labels like 0/1/2 are arbitrary, so "A"->0 vs "A"->1 must not
matter). A `collar` (seconds, each side of every reference boundary) is
excluded from scoring because hand-labelled boundaries are never exact.

Also reported, because ARIAD cares about *roles* more than raw clusters:

  - role_purity: the best role accuracy any role-assignment step could reach
    on top of this clustering -- each hypothesis speaker is given the
    majority reference role of the time it covers. Over-segmentation (one
    doctor split into two clusters) hurts DER but not role_purity, since
    both clusters still map to "doctor"; a cluster that mixes doctor and
    patient speech hurts both. This separates "clinician has to merge some
    labels" (annoying) from "clusters are wrong" (unsafe).
  - overlap_recall: share of reference overlap time where the hypothesis
    also has 2+ speakers active. None when the reference has no overlap
    (true of all current synthetic fixtures).

Pure Python, no pyannote/sherpa/numpy import -- unit-testable without models
(apps/api/tests/test_diarization_metrics.py), engine-agnostic.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import NamedTuple


class Turn(NamedTuple):
    start: float
    end: float
    speaker: str
    role: str | None = None  # reference only; hypothesis turns leave it None


@dataclass
class DiarizationScore:
    der: float | None
    missed: float  # seconds
    false_alarm: float
    confusion: float
    scored_speech: float  # reference speech seconds inside the scored region
    ref_speakers: int
    hyp_speakers: int
    role_purity: float | None
    overlap_recall: float | None


def turns_from_fixture(data: dict | list) -> list[Turn]:
    """tests/fixtures/audio/*.transcript.json -> reference turns.
    Accepts either {"segments": [...]} or a bare list of segments."""
    segments = data["segments"] if isinstance(data, dict) else data
    return [
        Turn(float(s["start"]), float(s["end"]), str(s["speaker"]), s.get("expected_role"))
        for s in segments
    ]


def _active(turns: Sequence[Turn], t: float) -> list[Turn]:
    return [turn for turn in turns if turn.start <= t < turn.end]


def _optimal_mapping(overlap: dict[tuple[str, str], float], ref_spk: list[str], hyp_spk: list[str]) -> dict[str, str]:
    """ref speaker -> hyp speaker, one-to-one, maximizing total co-active time.
    Bitmask DP over hypothesis speakers (exact; fine for the <=15 speakers a
    consultation has), greedy fallback beyond that."""
    if len(hyp_spk) > 15:
        mapping, used = {}, set()
        for (r, h), _ in sorted(overlap.items(), key=lambda kv: -kv[1]):
            if r not in mapping and h not in used:
                mapping[r] = h
                used.add(h)
        return mapping

    best: dict[int, tuple[float, dict[str, str]]] = {0: (0.0, {})}
    for r in ref_spk:
        nxt: dict[int, tuple[float, dict[str, str]]] = {}
        for mask, (score, mp) in best.items():
            # option: leave this ref speaker unmapped
            if mask not in nxt or nxt[mask][0] < score:
                nxt[mask] = (score, mp)
            for j, h in enumerate(hyp_spk):
                if mask & (1 << j):
                    continue
                m2 = mask | (1 << j)
                s2 = score + overlap.get((r, h), 0.0)
                if m2 not in nxt or nxt[m2][0] < s2:
                    nxt[m2] = (s2, {**mp, r: h})
        best = nxt
    return max(best.values(), key=lambda v: v[0])[1]


def compute_der(
    reference: Iterable[Turn],
    hypothesis: Iterable[Turn],
    collar: float = 0.25,
    frame: float = 0.01,
) -> DiarizationScore:
    ref = [t for t in reference if t.end > t.start]
    hyp = [t for t in hypothesis if t.end > t.start]
    ref_spk = sorted({t.speaker for t in ref})
    hyp_spk = sorted({t.speaker for t in hyp})

    end_time = max([t.end for t in ref] + [t.end for t in hyp] + [0.0])
    boundaries = [b for t in ref for b in (t.start, t.end)]
    n_frames = int(round(end_time / frame))

    # Pass 1: per-frame active speakers + co-activity for the speaker mapping.
    frames: list[tuple[list[Turn], list[Turn]]] = []
    overlap: dict[tuple[str, str], float] = defaultdict(float)
    for i in range(n_frames):
        t = (i + 0.5) * frame
        if collar > 0 and any(abs(t - b) < collar for b in boundaries):
            continue  # not scored
        r_act, h_act = _active(ref, t), _active(hyp, t)
        frames.append((r_act, h_act))
        for r in {x.speaker for x in r_act}:
            for h in {x.speaker for x in h_act}:
                overlap[(r, h)] += frame

    mapping = _optimal_mapping(overlap, ref_spk, hyp_spk)

    # Pass 2: miss / false alarm / confusion, NIST-style per frame.
    missed = false_alarm = confusion = scored = 0.0
    ov_total = ov_hit = 0.0
    hyp_role_time: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r_act, h_act in frames:
        r_set = {x.speaker for x in r_act}
        h_set = {x.speaker for x in h_act}
        n_ref, n_hyp = len(r_set), len(h_set)
        n_correct = sum(1 for r in r_set if mapping.get(r) in h_set)
        scored += n_ref * frame
        missed += max(0, n_ref - n_hyp) * frame
        false_alarm += max(0, n_hyp - n_ref) * frame
        confusion += (min(n_ref, n_hyp) - n_correct) * frame
        if n_ref >= 2:
            ov_total += frame
            if n_hyp >= 2:
                ov_hit += frame
        # role purity: only frames with exactly one reference speaker
        if n_ref == 1 and r_act[0].role is not None:
            for h in h_set:
                hyp_role_time[h][r_act[0].role] += frame

    role_purity = None
    role_total = sum(sum(v.values()) for v in hyp_role_time.values())
    if role_total > 0:
        role_purity = sum(max(v.values()) for v in hyp_role_time.values()) / role_total

    return DiarizationScore(
        der=(missed + false_alarm + confusion) / scored if scored > 0 else None,
        missed=round(missed, 3),
        false_alarm=round(false_alarm, 3),
        confusion=round(confusion, 3),
        scored_speech=round(scored, 3),
        ref_speakers=len(ref_spk),
        hyp_speakers=len(hyp_spk),
        role_purity=role_purity,
        overlap_recall=ov_hit / ov_total if ov_total > 0 else None,
    )

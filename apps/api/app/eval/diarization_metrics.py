"""tasks/07_NOISY_DIARIZATION_EVAL.md: frame-based Diarization Error Rate
(docs/TESTING_AND_EVALS.md names DER/speaker confusion as the diarization
metric) plus one ARIAD-specific number, background leakage.

DER follows the usual NIST md-eval definition: per frame, with N_ref/N_hyp
active speakers and N_correct of them matched under one global optimal
ref->hyp speaker mapping,
  missed      = max(0, N_ref - N_hyp)
  false alarm = max(0, N_hyp - N_ref)
  confusion   = min(N_ref, N_hyp) - N_correct
  DER         = (missed + false alarm + confusion) / sum(N_ref)
Overlapped speech counts once per speaker. Frames within `collar` seconds of
any reference boundary are excluded (0.25 s is the common NIST setting).

Background leakage: a reference segment marked `background=True` is speech
that is not part of this encounter (the neighbouring bed's rounds). DER
alone can't say whether that speech ended up under *our* doctor's/patient's
label, which is the clinically harmful case (it would enter the transcript
as if they said it). Leakage = share of background-only reference time that
the hypothesis labels with a speaker mapped to a foreground reference
speaker.

Pure (numpy only) -- unit-testable without any diarization engine
(see apps/api/tests/test_diarization_metrics.py).
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# 4 reference speakers vs 10 hypothesis clusters = 5040 mappings; anything
# far beyond that means the engine output is broken, not that we should wait.
_MAX_MAPPINGS = 1_000_000


@dataclass(frozen=True)
class SpeakerSegment:
    start: float
    end: float
    speaker: str
    background: bool = False


@dataclass(frozen=True)
class DiarizationScore:
    missed_seconds: float
    false_alarm_seconds: float
    confusion_seconds: float
    reference_seconds: float
    der: float
    # Background-only reference time and how much of it the hypothesis put
    # under a foreground speaker's label. leakage is None when the
    # reference has no background-only time.
    background_seconds: float
    background_leaked_seconds: float
    background_leakage: float | None
    reference_speakers: int
    hypothesis_speakers: int
    mapping: dict[str, str]


def _activity(
    segments: Sequence[SpeakerSegment], speakers: list[str], n_frames: int, frame: float
) -> np.ndarray:
    index = {spk: i for i, spk in enumerate(speakers)}
    active = np.zeros((len(speakers), n_frames), dtype=bool)
    for seg in segments:
        lo = max(0, int(round(seg.start / frame)))
        hi = min(n_frames, int(round(seg.end / frame)))
        if hi > lo:
            active[index[seg.speaker], lo:hi] = True
    return active


def _collar_mask(segments: Sequence[SpeakerSegment], n_frames: int, frame: float, collar: float) -> np.ndarray:
    scored = np.ones(n_frames, dtype=bool)
    if collar <= 0:
        return scored
    for seg in segments:
        for boundary in (seg.start, seg.end):
            lo = max(0, int(round((boundary - collar) / frame)))
            hi = min(n_frames, int(round((boundary + collar) / frame)))
            scored[lo:hi] = False
    return scored


def _optimal_mapping(cooccurrence: np.ndarray) -> list[tuple[int, int]]:
    """Exhaustive search over one-to-one ref->hyp mappings maximizing total
    co-occurring frames. Speaker counts here are small (<= 4 reference by
    product scope), so this stays exact without pulling in scipy."""
    n_ref, n_hyp = cooccurrence.shape
    if n_ref == 0 or n_hyp == 0:
        return []
    small, large = min(n_ref, n_hyp), max(n_ref, n_hyp)
    if np.prod(range(large - small + 1, large + 1), dtype=float) > _MAX_MAPPINGS:
        raise ValueError(f"too many speaker mappings to search ({n_ref} ref x {n_hyp} hyp)")

    best_score, best_pairs = -1, []
    if n_ref <= n_hyp:
        for hyp_ids in itertools.permutations(range(n_hyp), n_ref):
            score = int(sum(cooccurrence[r, h] for r, h in enumerate(hyp_ids)))
            if score > best_score:
                best_score, best_pairs = score, list(enumerate(hyp_ids))
    else:
        for ref_ids in itertools.permutations(range(n_ref), n_hyp):
            score = int(sum(cooccurrence[r, h] for h, r in enumerate(ref_ids)))
            if score > best_score:
                best_score, best_pairs = score, [(r, h) for h, r in enumerate(ref_ids)]
    return [(r, h) for r, h in best_pairs if cooccurrence[r, h] > 0]


def score_diarization(
    reference: Sequence[SpeakerSegment],
    hypothesis: Sequence[SpeakerSegment],
    collar: float = 0.25,
    frame: float = 0.01,
) -> DiarizationScore:
    ref_speakers = sorted({s.speaker for s in reference})
    hyp_speakers = sorted({s.speaker for s in hypothesis})
    background_speakers = {s.speaker for s in reference if s.background}
    end = max([s.end for s in reference] + [s.end for s in hypothesis] + [0.0])
    n_frames = int(np.ceil(end / frame)) + 1

    ref = _activity(reference, ref_speakers, n_frames, frame)
    hyp = _activity(hypothesis, hyp_speakers, n_frames, frame)
    scored = _collar_mask(reference, n_frames, frame, collar)
    ref, hyp = ref[:, scored], hyp[:, scored]

    cooccurrence = ref.astype(np.int64) @ hyp.T.astype(np.int64)
    pairs = _optimal_mapping(cooccurrence)
    correct = int(sum(cooccurrence[r, h] for r, h in pairs))

    n_ref, n_hyp = ref.sum(axis=0), hyp.sum(axis=0)
    missed = int(np.maximum(n_ref - n_hyp, 0).sum())
    false_alarm = int(np.maximum(n_hyp - n_ref, 0).sum())
    confusion = int(np.minimum(n_ref, n_hyp).sum()) - correct
    total = int(n_ref.sum())

    is_background = np.array([spk in background_speakers for spk in ref_speakers], dtype=bool)
    background_only = ref[is_background].any(axis=0) & ~ref[~is_background].any(axis=0)
    foreground_hyp = [h for r, h in pairs if not is_background[r]]
    leaked = background_only & hyp[foreground_hyp].any(axis=0) if foreground_hyp else np.zeros_like(background_only)

    background_frames = int(background_only.sum())
    leaked_frames = int(leaked.sum())
    return DiarizationScore(
        missed_seconds=missed * frame,
        false_alarm_seconds=false_alarm * frame,
        confusion_seconds=confusion * frame,
        reference_seconds=total * frame,
        der=(missed + false_alarm + confusion) / total if total else 0.0,
        background_seconds=background_frames * frame,
        background_leaked_seconds=leaked_frames * frame,
        background_leakage=leaked_frames / background_frames if background_frames else None,
        reference_speakers=len(ref_speakers),
        hypothesis_speakers=len(hyp_speakers),
        mapping={ref_speakers[r]: hyp_speakers[h] for r, h in pairs},
    )

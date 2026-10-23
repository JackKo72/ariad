"""Doctor-voice enrollment scoring -- an *evaluation* of whether a doctor's
pre-recorded voiceprint can (a) pick out the doctor's diarization clusters
and (b) flag small foreign clusters (next-room speech, passers-by) as
contamination. Opt-in research tool only: docs/PRODUCT.md and
docs/AI_PIPELINE.md keep voice-biometric identification out of the MVP
pipeline, and nothing here is wired into it. If the numbers justify it, that
is a product decision to record in docs, not something this module enables.

How it works (no model training -- "enrollment" is the standard approach):
  1. voiceprint = mean of L2-normalized speaker embeddings from the doctor's
     clean sample clips (same embedding model the diarizer already uses).
  2. Each diarization cluster gets a centroid embedding (several turns, not
     just the longest one -- tasks/03 section on robust centroids).
  3. cosine(cluster, voiceprint) >= threshold          -> "doctor"
     otherwise, cluster's share of speech < min_share  -> "contamination"
     otherwise                                         -> "other"
     ("other" = patient/guardian; telling those apart is not attempted.)
     Several clusters may be "doctor" -- that also auto-merges a
     doctor who was over-segmented into two clusters.
  4. label_turns(): the same voiceprint test per utterance, so a cluster
     that wrongly merged doctor and patient still gets split.

Scoring is time-weighted against a reference whose turns carry
`expected_role` ("doctor", "patient", "guardian", or "contamination" for
injected foreign speech). Pure Python; unit tests need no model.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.eval.diarization_metrics import Turn

Label = Literal["doctor", "other", "contamination"]


@dataclass
class ClusterInfo:
    embedding: list[float]
    seconds: float  # total speech time of this cluster in the recording


@dataclass
class ClusterDecision:
    label: Label
    similarity: float  # cosine to the doctor voiceprint
    share: float  # fraction of all hypothesis speech time


@dataclass
class EnrollmentScore:
    doctor_recall: float | None  # reference doctor time labelled doctor
    doctor_precision: float | None  # doctor-labelled time that really is the doctor
    contamination_kept: float | None  # injected foreign time that survived (lower = better)
    conversation_dropped: float | None  # real conversation time thrown out (lower = better)


def l2_normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm > 0 else list(vector)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(l2_normalize(a), l2_normalize(b), strict=True))


def build_voiceprint(embeddings: Sequence[Sequence[float]]) -> list[float]:
    """Mean of normalized embeddings, renormalized. Raises on empty input --
    a doctor with no usable sample clip must not get a silent zero vector."""
    if not embeddings:
        raise ValueError("no embeddings to build a voiceprint from")
    normed = [l2_normalize(e) for e in embeddings]
    return l2_normalize([sum(col) / len(normed) for col in zip(*normed, strict=True)])


def label_clusters(
    clusters: dict[str, ClusterInfo],
    voiceprint: Sequence[float],
    threshold: float = 0.5,
    min_share: float = 0.1,
) -> dict[str, ClusterDecision]:
    total = sum(c.seconds for c in clusters.values()) or 1.0
    decisions: dict[str, ClusterDecision] = {}
    for name, info in clusters.items():
        sim = cosine(info.embedding, voiceprint)
        share = info.seconds / total
        if sim >= threshold:
            label: Label = "doctor"
        elif share < min_share:
            label = "contamination"
        else:
            label = "other"
        decisions[name] = ClusterDecision(label, sim, share)
    return decisions


def label_turns(
    turn_similarities: Sequence[float | None],
    turn_clusters: Sequence[str],
    cluster_decisions: dict[str, ClusterDecision],
    threshold: float = 0.5,
) -> list[ClusterDecision]:
    """Per-utterance doctor decision, for when the diarizer merged doctor and
    patient into one cluster (seen in the first synthetic run) -- a cluster
    label can't split that, but each turn compared to the voiceprint can.

    sim >= threshold                  -> "doctor" (whatever its cluster says)
    no sim (turn too short to embed)  -> inherits its cluster's label
    cluster flagged "contamination"   -> stays "contamination"
    otherwise                         -> "other" (even inside a "doctor" cluster)
    """
    decisions = []
    for sim, cluster in zip(turn_similarities, turn_clusters, strict=True):
        parent = cluster_decisions[cluster]
        if sim is None:
            decisions.append(parent)
            continue
        if sim >= threshold:
            label: Label = "doctor"
        elif parent.label == "contamination":
            label = "contamination"
        else:
            label = "other"
        decisions.append(ClusterDecision(label, sim, parent.share))
    return decisions


def _frames(reference: Sequence[Turn], hypothesis: Sequence[Turn], collar: float, frame: float):
    """Yields (reference roles active, hypothesis speakers active) per scored frame."""
    end = max([t.end for t in reference] + [t.end for t in hypothesis] + [0.0])
    bounds = [b for t in reference for b in (t.start, t.end)]
    for i in range(round(end / frame)):
        t = (i + 0.5) * frame
        if collar > 0 and any(abs(t - b) < collar for b in bounds):
            continue
        yield (
            {r.role for r in reference if r.start <= t < r.end},
            {h.speaker for h in hypothesis if h.start <= t < h.end},
        )


def cluster_majority_roles(
    reference: Sequence[Turn], hypothesis: Sequence[Turn], frame: float = 0.01
) -> dict[str, str]:
    """Hypothesis cluster -> the reference role it overlaps most (for
    reporting similarity margins; collar not applied)."""
    time: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for roles, speakers in _frames(reference, hypothesis, 0.0, frame):
        for s in speakers:
            for r in roles:
                time[s][r] += frame
    return {s: max(v, key=v.get) for s, v in time.items()}


def similarity_margin(decisions: dict[str, ClusterDecision], majority_roles: dict[str, str]) -> float | None:
    """min(similarity of true-doctor clusters) - max(similarity of the rest).
    Positive = some threshold separates them perfectly on this recording;
    the size of the gap says how much room there is for real-world noise."""
    doctor = [d.similarity for s, d in decisions.items() if majority_roles.get(s) == "doctor"]
    rest = [d.similarity for s, d in decisions.items() if majority_roles.get(s) not in (None, "doctor")]
    if not doctor or not rest:
        return None
    return min(doctor) - max(rest)


def score_enrollment(
    reference: Sequence[Turn],
    hypothesis: Sequence[Turn],
    decisions: dict[str, ClusterDecision],
    collar: float = 0.25,
    frame: float = 0.01,
) -> EnrollmentScore:
    ref_doctor = doctor_hit = labelled_doctor = labelled_doctor_true = 0.0
    contam = contam_kept = convo = convo_dropped = 0.0
    for roles, speakers in _frames(reference, hypothesis, collar, frame):
        labels = {decisions[s].label for s in speakers if s in decisions}
        is_doctor_label = "doctor" in labels
        kept = bool(labels & {"doctor", "other"})
        if "doctor" in roles:
            ref_doctor += frame
            doctor_hit += frame if is_doctor_label else 0.0
        if is_doctor_label:
            labelled_doctor += frame
            labelled_doctor_true += frame if "doctor" in roles else 0.0
        if "contamination" in roles and len(roles) == 1:
            contam += frame
            contam_kept += frame if kept else 0.0
        if roles - {"contamination"}:
            convo += frame
            convo_dropped += frame if labels and not kept else 0.0

    def ratio(num: float, den: float) -> float | None:
        return num / den if den > 0 else None

    return EnrollmentScore(
        doctor_recall=ratio(doctor_hit, ref_doctor),
        doctor_precision=ratio(labelled_doctor_true, labelled_doctor),
        contamination_kept=ratio(contam_kept, contam),
        conversation_dropped=ratio(convo_dropped, convo),
    )

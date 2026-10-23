"""Unit: app.eval.doctor_enrollment -- voiceprint, cluster labelling and
time-weighted scoring on hand-made embeddings/turns. No model needed."""

import pytest

from app.eval.diarization_metrics import Turn
from app.eval.doctor_enrollment import (
    ClusterDecision,
    ClusterInfo,
    build_voiceprint,
    cluster_majority_roles,
    cosine,
    label_clusters,
    label_turns,
    score_enrollment,
    similarity_margin,
)

DOCTOR = [1.0, 0.0, 0.0]
PATIENT = [0.0, 1.0, 0.0]
NEIGHBOR = [0.0, 0.0, 1.0]


def test_cosine_and_voiceprint():
    assert cosine([2.0, 0.0], [5.0, 0.0]) == pytest.approx(1.0)
    assert cosine(DOCTOR, PATIENT) == pytest.approx(0.0)
    vp = build_voiceprint([[1.0, 0.1, 0.0], [1.0, -0.1, 0.0]])
    assert cosine(vp, DOCTOR) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        build_voiceprint([])


def test_label_clusters_doctor_other_contamination():
    clusters = {
        "0": ClusterInfo(DOCTOR, 50.0),
        "1": ClusterInfo(PATIENT, 45.0),
        "2": ClusterInfo(NEIGHBOR, 5.0),  # 5% of speech -> contamination
    }
    d = label_clusters(clusters, DOCTOR, threshold=0.5, min_share=0.1)
    assert {k: v.label for k, v in d.items()} == {"0": "doctor", "1": "other", "2": "contamination"}
    assert d["2"].share == pytest.approx(0.05)


def test_over_segmented_doctor_both_clusters_become_doctor():
    clusters = {"0": ClusterInfo([1.0, 0.1, 0.0], 30.0), "1": ClusterInfo([1.0, -0.1, 0.0], 30.0)}
    d = label_clusters(clusters, DOCTOR)
    assert {v.label for v in d.values()} == {"doctor"}


REF = [
    Turn(0.0, 10.0, "A", "doctor"),
    Turn(10.0, 20.0, "B", "patient"),
    Turn(20.0, 24.0, "X", "contamination"),
]
HYP = [Turn(0.0, 10.0, "0"), Turn(10.0, 20.0, "1"), Turn(20.0, 24.0, "2")]


def _decisions(**labels):
    return {k: ClusterDecision(v, 0.0, 0.0) for k, v in labels.items()}


def test_perfect_labelling():
    s = score_enrollment(REF, HYP, _decisions(**{"0": "doctor", "1": "other", "2": "contamination"}), collar=0)
    assert s.doctor_recall == pytest.approx(1.0)
    assert s.doctor_precision == pytest.approx(1.0)
    assert s.contamination_kept == pytest.approx(0.0)
    assert s.conversation_dropped == pytest.approx(0.0)


def test_contamination_kept_and_patient_dropped():
    s = score_enrollment(REF, HYP, _decisions(**{"0": "doctor", "1": "contamination", "2": "other"}), collar=0)
    assert s.contamination_kept == pytest.approx(1.0)
    assert s.conversation_dropped == pytest.approx(10 / 20)


def test_patient_mislabelled_as_doctor_lowers_precision():
    s = score_enrollment(REF, HYP, _decisions(**{"0": "doctor", "1": "doctor", "2": "contamination"}), collar=0)
    assert s.doctor_recall == pytest.approx(1.0)
    assert s.doctor_precision == pytest.approx(10 / 20)


def test_label_turns_splits_merged_doctor_patient_cluster():
    # diarizer put doctor and patient in one cluster "0" labelled doctor
    parents = {"0": ClusterDecision("doctor", 0.8, 0.9), "9": ClusterDecision("contamination", 0.1, 0.05)}
    out = label_turns(
        turn_similarities=[0.85, 0.25, None, 0.20, 0.70],
        turn_clusters=["0", "0", "0", "9", "9"],
        cluster_decisions=parents,
        threshold=0.5,
    )
    assert [d.label for d in out] == ["doctor", "other", "doctor", "contamination", "doctor"]
    assert out[1].similarity == pytest.approx(0.25)
    assert out[2] is parents["0"]  # too short to embed -> inherits cluster


def test_turn_level_scoring_fixes_merged_cluster():
    hyp_one_cluster = [Turn(0.0, 10.0, "0"), Turn(10.0, 20.0, "0")]
    ref = REF[:2]
    cluster_level = score_enrollment(ref, hyp_one_cluster, _decisions(**{"0": "doctor"}), collar=0)
    assert cluster_level.doctor_precision == pytest.approx(0.5)
    per_turn = [Turn(t.start, t.end, f"0.{i}") for i, t in enumerate(hyp_one_cluster)]
    turn_level = score_enrollment(ref, per_turn, _decisions(**{"0.0": "doctor", "0.1": "other"}), collar=0)
    assert turn_level.doctor_precision == pytest.approx(1.0)
    assert turn_level.doctor_recall == pytest.approx(1.0)


def test_majority_roles_and_margin():
    roles = cluster_majority_roles(REF, HYP)
    assert roles == {"0": "doctor", "1": "patient", "2": "contamination"}
    d = {
        "0": ClusterDecision("doctor", 0.8, 0.0),
        "1": ClusterDecision("other", 0.3, 0.0),
        "2": ClusterDecision("contamination", 0.1, 0.0),
    }
    assert similarity_margin(d, roles) == pytest.approx(0.5)

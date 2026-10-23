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


def test_majority_roles_and_margin():
    roles = cluster_majority_roles(REF, HYP)
    assert roles == {"0": "doctor", "1": "patient", "2": "contamination"}
    d = {
        "0": ClusterDecision("doctor", 0.8, 0.0),
        "1": ClusterDecision("other", 0.3, 0.0),
        "2": ClusterDecision("contamination", 0.1, 0.0),
    }
    assert similarity_margin(d, roles) == pytest.approx(0.5)

"""Unit: app.eval.diarization_metrics -- frame-based DER, speaker mapping,
role purity, overlap recall. Hand-computed synthetic cases, no model needed.
collar=0 unless a test is about the collar, so expected seconds are exact."""

import json
from pathlib import Path

import pytest

from app.eval.diarization_metrics import Turn, compute_der, turns_from_fixture

REF = [
    Turn(0.0, 10.0, "A", "doctor"),
    Turn(10.0, 20.0, "B", "patient"),
]


def test_perfect_match_with_different_labels_is_zero():
    hyp = [Turn(0.0, 10.0, "1"), Turn(10.0, 20.0, "0")]
    s = compute_der(REF, hyp, collar=0)
    assert s.der == pytest.approx(0.0)
    assert (s.ref_speakers, s.hyp_speakers) == (2, 2)
    assert s.role_purity == pytest.approx(1.0)


def test_missed_speech():
    hyp = [Turn(0.0, 10.0, "0"), Turn(10.0, 15.0, "1")]  # last 5s of B missing
    s = compute_der(REF, hyp, collar=0)
    assert s.missed == pytest.approx(5.0)
    assert s.false_alarm == pytest.approx(0.0)
    assert s.der == pytest.approx(5 / 20)


def test_false_alarm():
    hyp = [Turn(0.0, 10.0, "0"), Turn(10.0, 20.0, "1"), Turn(20.0, 24.0, "1")]
    s = compute_der(REF, hyp, collar=0)
    assert s.false_alarm == pytest.approx(4.0)
    assert s.der == pytest.approx(4 / 20)


def test_confusion_when_one_turn_gets_wrong_speaker():
    ref = REF + [Turn(20.0, 30.0, "A", "doctor")]
    hyp = [Turn(0.0, 10.0, "0"), Turn(10.0, 20.0, "1"), Turn(20.0, 30.0, "1")]
    s = compute_der(ref, hyp, collar=0)
    assert s.confusion == pytest.approx(10.0)
    assert s.der == pytest.approx(10 / 30)
    # cluster "1" holds 10s patient + 10s doctor -> best role guess right half the time
    assert s.role_purity == pytest.approx(20 / 30)


def test_over_segmentation_hurts_der_but_not_role_purity():
    ref = [Turn(0.0, 10.0, "A", "doctor")]
    hyp = [Turn(0.0, 5.0, "0"), Turn(5.0, 10.0, "1")]  # one doctor split in two
    s = compute_der(ref, hyp, collar=0)
    assert s.confusion == pytest.approx(5.0)
    assert s.der == pytest.approx(0.5)
    assert s.hyp_speakers == 2
    assert s.role_purity == pytest.approx(1.0)


def test_collar_excludes_boundaries():
    hyp = [Turn(0.0, 10.2, "0"), Turn(10.2, 20.0, "1")]  # boundary off by 0.2s
    assert compute_der(REF, hyp, collar=0).confusion == pytest.approx(0.2)
    assert compute_der(REF, hyp, collar=0.25).der == pytest.approx(0.0)


def test_overlap_recall():
    ref = [Turn(0.0, 10.0, "A", "doctor"), Turn(8.0, 12.0, "B", "patient")]
    hyp_detects = [Turn(0.0, 10.0, "0"), Turn(8.0, 12.0, "1")]
    hyp_misses = [Turn(0.0, 10.0, "0"), Turn(10.0, 12.0, "1")]
    assert compute_der(ref, hyp_detects, collar=0).overlap_recall == pytest.approx(1.0)
    assert compute_der(ref, hyp_misses, collar=0).overlap_recall == pytest.approx(0.0)
    assert compute_der(REF, REF, collar=0).overlap_recall is None


def test_empty_hypothesis_is_all_missed():
    s = compute_der(REF, [], collar=0)
    assert s.der == pytest.approx(1.0)
    assert s.hyp_speakers == 0


def test_fixture_loads_and_scores_itself_perfectly():
    path = Path(__file__).resolve().parents[3] / "tests/fixtures/audio/sample_consultation.transcript.json"
    ref = turns_from_fixture(json.loads(path.read_text()))
    assert {t.role for t in ref} == {"doctor", "patient"}
    hyp = [Turn(t.start, t.end, {"A": "0", "B": "1"}[t.speaker]) for t in ref]
    assert compute_der(ref, hyp).der == pytest.approx(0.0)

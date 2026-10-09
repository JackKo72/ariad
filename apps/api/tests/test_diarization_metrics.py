"""Unit: app.eval.diarization_metrics (tasks/07_NOISY_DIARIZATION_EVAL.md).

Hand-countable timelines, collar=0 unless the collar itself is under test --
pure functions, no diarization engine needed.
"""

import pytest

from app.eval.diarization_metrics import SpeakerSegment as S
from app.eval.diarization_metrics import score_diarization

REF_TWO_SPEAKERS = [S(0.0, 4.0, "A"), S(4.0, 10.0, "B")]


def test_perfect_match_under_different_labels_is_zero():
    hyp = [S(0.0, 4.0, "speaker_1"), S(4.0, 10.0, "speaker_0")]
    score = score_diarization(REF_TWO_SPEAKERS, hyp, collar=0)
    assert score.der == 0
    assert score.mapping == {"A": "speaker_1", "B": "speaker_0"}


def test_empty_hypothesis_is_all_missed():
    score = score_diarization(REF_TWO_SPEAKERS, [], collar=0)
    assert score.missed_seconds == pytest.approx(10.0)
    assert score.der == pytest.approx(1.0)


def test_hypothesis_speech_in_silence_is_false_alarm():
    ref = [S(0.0, 4.0, "A")]
    hyp = [S(0.0, 4.0, "x"), S(6.0, 8.0, "x")]
    score = score_diarization(ref, hyp, collar=0)
    assert score.false_alarm_seconds == pytest.approx(2.0)
    assert score.der == pytest.approx(0.5)


def test_one_cluster_for_two_speakers_is_confusion():
    # Under-segmentation: the engine merges A and B. The best mapping keeps
    # B's 6 s, so A's 4 s count as confusion.
    score = score_diarization(REF_TWO_SPEAKERS, [S(0.0, 10.0, "x")], collar=0)
    assert score.confusion_seconds == pytest.approx(4.0)
    assert score.missed_seconds == 0
    assert score.der == pytest.approx(0.4)


def test_extra_hypothesis_cluster_is_confusion():
    # Over-segmentation: B split into two clusters; only one can map to B.
    hyp = [S(0.0, 4.0, "x"), S(4.0, 8.0, "y"), S(8.0, 10.0, "z")]
    score = score_diarization(REF_TWO_SPEAKERS, hyp, collar=0)
    assert score.hypothesis_speakers == 3
    assert score.confusion_seconds == pytest.approx(2.0)


def test_overlap_counts_each_speaker():
    ref = [S(0.0, 4.0, "A"), S(2.0, 4.0, "B")]
    hyp = [S(0.0, 4.0, "x")]  # misses B's overlapped 2 s
    score = score_diarization(ref, hyp, collar=0)
    assert score.reference_seconds == pytest.approx(6.0)
    assert score.missed_seconds == pytest.approx(2.0)


def test_collar_forgives_boundary_jitter():
    hyp = [S(0.0, 4.2, "x"), S(4.2, 10.0, "y")]
    assert score_diarization(REF_TWO_SPEAKERS, hyp, collar=0).der > 0
    assert score_diarization(REF_TWO_SPEAKERS, hyp, collar=0.25).der == 0


REF_WITH_NEIGHBOUR = [S(0.0, 4.0, "A"), S(4.0, 8.0, "B"), S(8.0, 10.0, "BG", background=True)]


def test_neighbour_merged_into_our_doctor_is_leakage():
    hyp = [S(0.0, 4.0, "x"), S(4.0, 8.0, "y"), S(8.0, 10.0, "x")]
    score = score_diarization(REF_WITH_NEIGHBOUR, hyp, collar=0)
    assert score.background_seconds == pytest.approx(2.0)
    assert score.background_leakage == pytest.approx(1.0)


def test_neighbour_in_its_own_cluster_is_not_leakage():
    hyp = [S(0.0, 4.0, "x"), S(4.0, 8.0, "y"), S(8.0, 10.0, "z")]
    score = score_diarization(REF_WITH_NEIGHBOUR, hyp, collar=0)
    assert score.background_leakage == 0
    assert score.der == 0


def test_neighbour_not_detected_at_all_is_not_leakage():
    hyp = [S(0.0, 4.0, "x"), S(4.0, 8.0, "y")]
    score = score_diarization(REF_WITH_NEIGHBOUR, hyp, collar=0)
    assert score.background_leakage == 0
    assert score.missed_seconds == pytest.approx(2.0)


def test_no_background_reference_reports_none():
    assert score_diarization(REF_TWO_SPEAKERS, REF_TWO_SPEAKERS, collar=0).background_leakage is None

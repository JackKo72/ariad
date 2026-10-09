"""Unit: app.eval.noise_mix (tasks/07_NOISY_DIARIZATION_EVAL.md)."""

import numpy as np
import pytest

from app.eval.noise_mix import fit_length, mix_at_snr


def _snr_db(clean, mixed, mask=None):
    noise = mixed.astype(np.float64) - clean
    if mask is not None:
        clean = clean[mask]
    return 10 * np.log10(np.mean(clean**2) / np.mean(noise**2))


def test_fit_length_loops_and_trims():
    assert fit_length(np.array([1, 2, 3]), 7).tolist() == [1, 2, 3, 1, 2, 3, 1]
    assert fit_length(np.array([1, 2, 3]), 2).tolist() == [1, 2]


def test_fit_length_rejects_empty():
    with pytest.raises(ValueError):
        fit_length(np.array([]), 5)


@pytest.mark.parametrize("snr_db", [0, 5, 10])
def test_mix_hits_target_snr(snr_db):
    rng = np.random.default_rng(0)
    clean = 0.1 * rng.standard_normal(16000)
    mixed = mix_at_snr(clean, rng.standard_normal(4000), snr_db)
    assert len(mixed) == len(clean)
    assert _snr_db(clean, mixed) == pytest.approx(snr_db, abs=0.05)


def test_snr_is_measured_over_speech_mask_not_silence():
    rng = np.random.default_rng(1)
    clean = np.zeros(16000)
    clean[:4000] = 0.1 * rng.standard_normal(4000)
    mask = np.zeros(16000, dtype=bool)
    mask[:4000] = True
    mixed = mix_at_snr(clean, rng.standard_normal(16000), 5, clean_mask=mask)
    assert _snr_db(clean, mixed, mask) == pytest.approx(5, abs=0.1)


def test_clipping_guard_keeps_snr():
    # Same signals at 1/10 amplitude never clip; the loud mix must be exactly
    # that quiet mix scaled up (i.e. clean and noise scaled down together).
    rng = np.random.default_rng(2)
    clean = 0.9 * np.sign(rng.standard_normal(16000))
    noise = rng.standard_normal(16000)
    loud = mix_at_snr(clean, noise, 0)
    quiet = mix_at_snr(clean / 10, noise, 0)
    assert np.max(np.abs(loud)) == pytest.approx(0.99, abs=1e-6)
    assert loud / (loud[0] / quiet[0]) == pytest.approx(quiet, rel=1e-4, abs=1e-6)


def test_silent_interference_is_rejected():
    with pytest.raises(ValueError):
        mix_at_snr(np.ones(100) * 0.1, np.zeros(100), 5)

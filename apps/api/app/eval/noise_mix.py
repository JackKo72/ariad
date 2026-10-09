"""tasks/07_NOISY_DIARIZATION_EVAL.md: mix a clean synthetic encounter with
an interference signal (music, construction, a neighbouring conversation)
at an exact target SNR, so a diarization engine or a denoise setting can be
compared against known ground truth.

SNR is measured over the clean signal's *speech-active* samples when a mask
is given -- a whole-file RMS would be dragged down by the silent gaps
between turns and make every condition look noisier than its label says.

Pure (numpy only) -- see apps/api/tests/test_noise_mix.py.
"""

from __future__ import annotations

import numpy as np

_PEAK_LIMIT = 0.99


def fit_length(signal: np.ndarray, n_samples: int) -> np.ndarray:
    """Loops a shorter signal (or trims a longer one) to exactly n_samples."""
    if len(signal) == 0:
        raise ValueError("cannot fit an empty signal")
    repeats = int(np.ceil(n_samples / len(signal)))
    return np.tile(signal, repeats)[:n_samples]


def _power(signal: np.ndarray, mask: np.ndarray | None) -> float:
    selected = signal if mask is None else signal[mask]
    return float(np.mean(selected.astype(np.float64) ** 2)) if len(selected) else 0.0


def mix_at_snr(
    clean: np.ndarray,
    interference: np.ndarray,
    snr_db: float,
    clean_mask: np.ndarray | None = None,
    interference_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Returns clean + g * interference (float32, same length as clean), with
    g chosen so that 10*log10(P_clean / P_interference_scaled) == snr_db.
    Masks pick which samples count toward each side's power (e.g. only the
    neighbouring conversation's own speech turns). If the sum would clip,
    both sides are scaled down together, which keeps the SNR unchanged."""
    interference = fit_length(interference, len(clean))
    if interference_mask is not None:
        interference_mask = fit_length(interference_mask, len(clean))
    clean_power = _power(clean, clean_mask)
    interference_power = _power(interference, interference_mask)
    if clean_power == 0 or interference_power == 0:
        raise ValueError("clean and interference signals must both be non-silent")

    gain = np.sqrt(clean_power / (interference_power * 10 ** (snr_db / 10)))
    mixed = clean.astype(np.float64) + gain * interference.astype(np.float64)
    peak = float(np.max(np.abs(mixed)))
    if peak > _PEAK_LIMIT:
        mixed *= _PEAK_LIMIT / peak
    return mixed.astype(np.float32)

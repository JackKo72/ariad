"""tasks/06_ASR_OUTPUT_VERIFICATION.md: standard edit-distance-based WER/CER,
to replace the keyword-presence-only accuracy checks scripts/compare_asr_
accuracy.py had before (PASS/FAIL on a handful of clinical anchors, no
overall error-rate number). docs/TESTING_AND_EVALS.md already names CER as
the Korean-ASR priority metric ("한국어 전사는 WER보다 CER를 우선 기록한다");
WER is computed too, as a secondary/informational number, since Korean
word-spacing from ASR is inconsistent enough that CER remains the one to
act on.

Pure, no sherpa_onnx/faster_whisper import -- unit-testable without real
models (see apps/api/tests/test_asr_metrics.py), and reusable by any future
accuracy script regardless of ASR engine.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class EditRateResult:
    substitutions: int
    deletions: int
    insertions: int
    ref_length: int
    rate: float


def _edit_ops(ref: Sequence, hyp: Sequence) -> tuple[int, int, int]:
    """Standard Levenshtein DP, then backtrace to recover substitution/
    deletion/insertion counts (not just the total distance) -- ties prefer
    a match, then a substitution, then a deletion, then an insertion, the
    same convention common WER/CER tools use."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1])

    i, j = n, m
    substitutions = deletions = insertions = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1] and dp[i][j] == dp[i - 1][j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            substitutions += 1
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    return substitutions, deletions, insertions


def _rate(substitutions: int, deletions: int, insertions: int, ref_length: int) -> EditRateResult:
    errors = substitutions + deletions + insertions
    if ref_length:
        rate = errors / ref_length
    else:
        # Undefined (0/0) when both sides are empty, otherwise all of
        # hyp is an insertion against nothing to divide by -- report +inf
        # rather than a misleadingly finite number.
        rate = 0.0 if errors == 0 else float("inf")
    return EditRateResult(substitutions, deletions, insertions, ref_length, rate)


def compute_cer(reference: str, hypothesis: str) -> EditRateResult:
    """Character Error Rate. Whitespace is stripped from both sides first --
    ASR word-spacing in Korean is inconsistent even when the content is
    correct, so counting space characters as errors would be noise, not
    signal (same reasoning compare_asr_accuracy.py's existing `_normalize`
    already applies to its keyword checks)."""
    ref_chars = list(reference.replace(" ", ""))
    hyp_chars = list(hypothesis.replace(" ", ""))
    s, d, ins = _edit_ops(ref_chars, hyp_chars)
    return _rate(s, d, ins, len(ref_chars))


def compute_wer(reference: str, hypothesis: str) -> EditRateResult:
    """Word Error Rate, split on whitespace. Secondary/informational for
    Korean (see module docstring) -- CER is the one to act on."""
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    s, d, ins = _edit_ops(ref_words, hyp_words)
    return _rate(s, d, ins, len(ref_words))


def aggregate(results: list[EditRateResult]) -> EditRateResult:
    """Micro-average across segments: sum error counts and reference
    lengths first, then take one rate -- not the mean of per-segment rates,
    which would weight a 2-character segment equally to a 40-character one."""
    substitutions = sum(r.substitutions for r in results)
    deletions = sum(r.deletions for r in results)
    insertions = sum(r.insertions for r in results)
    ref_length = sum(r.ref_length for r in results)
    return _rate(substitutions, deletions, insertions, ref_length)

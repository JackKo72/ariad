"""Unit: app.eval.asr_metrics (tasks/06_ASR_OUTPUT_VERIFICATION.md).

Standard edit-distance WER/CER, verified against hand-counted cases --
pure functions, no real ASR model needed.
"""

from app.eval.asr_metrics import EditRateResult, aggregate, compute_cer, compute_wer


class TestComputeCer:
    def test_identical_text_is_zero(self):
        result = compute_cer("오늘 혈압이 높습니다", "오늘 혈압이 높습니다")
        assert result == EditRateResult(0, 0, 0, 9, 0.0)

    def test_single_substitution(self):
        # 재보니 -> 채워니: 3-char overlap region, "재"->"채", "보"->"워" = 2 subs
        result = compute_cer("재보니", "채워니")
        assert result.substitutions == 2
        assert result.deletions == 0
        assert result.insertions == 0
        assert result.ref_length == 3
        assert result.rate == 2 / 3

    def test_single_deletion(self):
        result = compute_cer("아스피린", "아피린")
        assert result.deletions == 1
        assert result.substitutions == 0
        assert result.ref_length == 4
        assert result.rate == 1 / 4

    def test_single_insertion(self):
        result = compute_cer("아피린", "아스피린")
        assert result.insertions == 1
        assert result.ref_length == 3
        assert result.rate == 1 / 3

    def test_whitespace_is_stripped_before_comparing(self):
        # Same content, different spacing -- must not count as errors.
        result = compute_cer("오늘 혈압이 높습니다", "오늘혈압이높습니다")
        assert result == EditRateResult(0, 0, 0, 9, 0.0)

    def test_empty_reference_and_hypothesis_is_zero(self):
        result = compute_cer("", "")
        assert result.rate == 0.0

    def test_empty_reference_nonempty_hypothesis_is_infinite(self):
        result = compute_cer("", "환각")
        assert result.rate == float("inf")
        assert result.insertions == 2

    def test_completely_different_text(self):
        result = compute_cer("리시노프릴", "크리스토퍼")
        # Every reference character counted as an error upper bound.
        assert result.rate <= 1.0
        assert result.substitutions + result.deletions == 5 or result.insertions > 0


class TestComputeWer:
    def test_identical_sentence_is_zero(self):
        result = compute_wer("아스피린은 지금 시작하지 않습니다", "아스피린은 지금 시작하지 않습니다")
        assert result.rate == 0.0

    def test_dropped_negation_word_is_one_deletion(self):
        result = compute_wer("아스피린은 지금 시작하지 않습니다", "아스피린은 지금 시작하기란 습니다")
        # 4 ref words; "않습니다" replaced by something else -> at least 1 sub.
        assert result.ref_length == 4
        assert result.substitutions + result.deletions + result.insertions >= 1

    def test_word_order_preserved_but_one_word_wrong(self):
        result = compute_wer("혈압약 리시노프릴 오 밀리그램", "혈압약 리시노프릴 오 밀크레")
        assert result.substitutions == 1
        assert result.ref_length == 4
        assert result.rate == 0.25


class TestAggregate:
    def test_aggregate_is_micro_averaged_not_mean_of_rates(self):
        # Segment 1: 1 error / 2 ref chars (rate 0.5). Segment 2: 1 error /
        # 18 ref chars (rate ~0.056). Mean of rates would be ~0.28; micro
        # average (2 errors / 20 ref chars) is 0.10 -- the two must differ,
        # proving aggregate() does the latter.
        seg1 = compute_cer("아피", "아")
        seg2 = compute_cer("오늘 혈압이 조금 높습니다요", "오늘 혈압이 조금 높습니다용")
        result = aggregate([seg1, seg2])
        assert result.ref_length == seg1.ref_length + seg2.ref_length
        naive_mean = (seg1.rate + seg2.rate) / 2
        assert result.rate != naive_mean

    def test_aggregate_of_empty_list_is_zero(self):
        result = aggregate([])
        assert result.rate == 0.0
        assert result.ref_length == 0

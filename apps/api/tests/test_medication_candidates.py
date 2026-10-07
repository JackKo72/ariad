"""Unit: app.pipeline.medication_candidates (tasks/06_ASR_OUTPUT_VERIFICATION.md
선택지 B -- 사전 기반 약명 fuzzy 교정, 원문은 절대 덮어쓰지 않고 후보만
반환한다)."""

from app.pipeline.medication_candidates import find_medication_candidates


class TestFindMedicationCandidates:
    def test_exact_dictionary_match_is_not_flagged(self):
        text = "혈압약 아스피린 을 드립니다"
        assert find_medication_candidates(text) == []

    def test_light_garble_is_caught_with_high_similarity(self):
        # "리시노프탈" differs from "리시노프릴" by one character (1/5 CER).
        text = "혈압약 리시노프탈 오 밀리그램을 드립니다"
        candidates = find_medication_candidates(text)
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.matched_span == "리시노프탈"
        assert candidate.suggested_name == "리시노프릴"
        assert candidate.similarity == 0.8

    def test_severe_garble_honestly_stays_below_threshold(self):
        # Real tasks/05 example: "리시노프릴" ASR'd as two separate, badly
        # garbled tokens. Similarity (~0.2) is nowhere near min_similarity
        # (0.6 default) -- this must NOT be falsely flagged as a confident
        # correction; fuzzy matching has real limits and must say so by
        # staying silent, not by guessing.
        text = "혈압약 리신 오프리오 를 드립니다"
        assert find_medication_candidates(text) == []

    def test_unrelated_text_returns_no_candidates(self):
        text = "오늘 날씨가 좋고 기분이 괜찮습니다"
        assert find_medication_candidates(text) == []

    def test_overlapping_windows_do_not_produce_duplicate_candidates(self):
        text = "혈압약 리시노프탈 오 밀리그램을 드립니다"
        candidates = find_medication_candidates(text)
        occupied_indices = set()
        for c in candidates:
            span_range = set(range(c.token_start_index, c.token_end_index))
            assert not (span_range & occupied_indices), "overlapping candidates were returned"
            occupied_indices |= span_range

    def test_custom_dictionary_is_injectable(self):
        text = "새로운약품 을 처방합니다"
        assert find_medication_candidates(text, dictionary=("아스피린",)) == []
        candidates = find_medication_candidates(text, dictionary=("새로운약픔",), min_similarity=0.5)
        assert len(candidates) == 1
        assert candidates[0].suggested_name == "새로운약픔"

    def test_min_similarity_threshold_is_respected(self):
        text = "혈압약 리시노프탈 오 밀리그램을 드립니다"
        # Raising the bar above the real similarity (0.8) must suppress the candidate.
        assert find_medication_candidates(text, min_similarity=0.95) == []

    def test_returned_candidates_are_sorted_by_token_position(self):
        text = "아목시실린 과 메트포르민 비슷한 아목시실림 비슷한 메트포르믐 을 드립니다"
        candidates = find_medication_candidates(text, min_similarity=0.6)
        positions = [c.token_start_index for c in candidates]
        assert positions == sorted(positions)

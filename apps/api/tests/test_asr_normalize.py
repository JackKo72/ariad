"""Unit: app.pipeline.asr_normalize (tasks/06_ASR_OUTPUT_VERIFICATION.md).

Covers the real "오 밀리그램" dose example this was built for, plus the
false-positive risks that shaped the design (an exclamation, an ordinary
word that happens to start with a digit-reading syllable) and the
documented out-of-scope case (a bare number with no unit-word neighbor).
"""

from app.pipeline.asr_normalize import _parse_sino_korean_number, normalize_korean_number_words


class TestParseSinoKoreanNumber:
    def test_single_digit(self):
        assert _parse_sino_korean_number("오") == 5

    def test_teen(self):
        assert _parse_sino_korean_number("십오") == 15

    def test_bare_ten(self):
        assert _parse_sino_korean_number("십") == 10

    def test_hundreds(self):
        assert _parse_sino_korean_number("백사십오") == 145

    def test_ninety_two(self):
        assert _parse_sino_korean_number("구십이") == 92

    def test_bare_hundred(self):
        assert _parse_sino_korean_number("백") == 100

    def test_invalid_double_digit_returns_none(self):
        # "일이" has no unit between the two digits -- ambiguous, must not guess.
        assert _parse_sino_korean_number("일이") is None

    def test_non_number_char_returns_none(self):
        assert _parse_sino_korean_number("오진") is None


class TestNormalizeKoreanNumberWords:
    def test_dose_before_milligram_is_normalized(self):
        text = "혈압약 리시노프릴 오 밀리그램을 하루 한 번 드세요"
        assert normalize_korean_number_words(text) == "혈압약 리시노프릴 5 밀리그램을 하루 한 번 드세요"

    def test_multi_syllable_dose_before_mg(self):
        assert normalize_korean_number_words("아목시실린 십오 mg") == "아목시실린 15 mg"

    def test_dose_before_count_unit_hoi(self):
        assert normalize_korean_number_words("하루 삼 회 복용") == "하루 3 회 복용"

    def test_bare_number_with_no_unit_neighbor_is_left_alone(self):
        # tasks/05's real "145에 92로" garble analog -- no unit word
        # directly follows either number word, so this stays untouched by
        # design (documented limitation, not a bug).
        text = "오늘 혈압을 재보니 백사십오에 구십이로 나왔습니다"
        assert normalize_korean_number_words(text) == text

    def test_exclamation_is_not_mistaken_for_a_dose(self):
        # "오!" (an exclamation) must never be rewritten to "5!" just
        # because it happens to be a bare Sino-Korean number-word syllable.
        text = "오! 알겠습니다"
        assert normalize_korean_number_words(text) == text

    def test_ordinary_word_sharing_a_digit_syllable_is_untouched(self):
        # "사과"(apple)/"이과"(science track) are not pure number tokens
        # (the trailing syllable isn't a digit/unit character), so the
        # whole-token purity check already protects them.
        assert normalize_korean_number_words("사과를 못 드셨나요") == "사과를 못 드셨나요"
        assert normalize_korean_number_words("이과 출신입니다") == "이과 출신입니다"

    def test_age_demographic_phrase_is_untouched(self):
        assert normalize_korean_number_words("이십대 환자입니다") == "이십대 환자입니다"

    def test_no_number_words_at_all_is_unchanged(self):
        text = "아스피린은 지금 시작하지 않습니다"
        assert normalize_korean_number_words(text) == text

    def test_last_token_number_word_with_no_following_token_is_untouched(self):
        assert normalize_korean_number_words("처방은 오") == "처방은 오"

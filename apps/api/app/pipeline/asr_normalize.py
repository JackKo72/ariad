"""tasks/06_ASR_OUTPUT_VERIFICATION.md: a deterministic, conservative
post-ASR normalization step -- the "제2단(second stage)" the user asked
about, scoped to the one case this investigation actually has real
evidence for: a Sino-Korean number word spoken right before a dose/
measurement unit (tasks/05's "오 밀리그램" example, and its sibling garbles
like "오오 밀크 레"/"오에구십"). This is a text-form rewrite of exactly what
was said, not a clinical-fact invention -- "오 밀리그램" and "5 밀리그램" mean
the same dose, so converting one spelling to the other never adds a value
that wasn't in the input (CLAUDE.md: "입력에 없는 ... 수치를 생성하지 않는다"
is about inventing a *different* value, not re-spelling the same one).

Deliberately NOT attempted here (scope left out, not silently covered):
  - A bare number phrase with no unit word next to it (tasks/05's "145에
    92로" blood-pressure garble) -- a Sino-Korean number word on its own
    is not safely distinguishable from an ordinary word that happens to
    start with the same syllable (e.g. the exclamation "오!", or words like
    "사과"/"이과" whose first syllable is also a digit reading). Requiring
    an adjacent known unit word is what makes this safe; a bare number has
    no such anchor, so it is left untouched rather than guessed at.
  - Native-Korean counting numbers (하나/둘/셋 for counting objects, e.g.
    "하루 한 번") -- different grammar, different risk profile, out of
    scope for this pass.
  - Decimals ("영점오") and anything beyond 만(10,000) -- not needed for
    clinical dose/vital-sign ranges, and adds parsing edge cases for no
    real benefit here.

Pure function, no sherpa_onnx/faster_whisper import -- unit-testable
without real models (see apps/api/tests/test_asr_normalize.py). Not wired
into any ASRProvider yet -- see tasks/06 for the measured before/after
comparison and the open question of whether/how to turn this on by default.
"""

from __future__ import annotations

_DIGIT_VALUES = {
    "영": 0, "일": 1, "이": 2, "삼": 3, "사": 4,
    "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9,
}
_UNIT_VALUES = {"십": 10, "백": 100, "천": 1000}
_BIG_UNIT_VALUES = {"만": 10000}
_NUMBER_CHARS = frozenset(_DIGIT_VALUES) | frozenset(_UNIT_VALUES) | frozenset(_BIG_UNIT_VALUES)

# Dose/measurement unit words a number word is considered safely numeric in
# front of. Narrow on purpose -- see module docstring.
_UNIT_WORD_PREFIXES = (
    "밀리그램", "mg", "그램", "밀리리터", "ml", "cc", "리터",
    "mmhg", "알", "정", "캡슐", "회", "번",
)


def _parse_sino_korean_number(run: str) -> int | None:
    """Parses a Sino-Korean number word made purely of _NUMBER_CHARS (e.g.
    "백사십오" -> 145, "오" -> 5, "십" -> 10). Returns None for an invalid
    pattern (e.g. two digits in a row with no unit between them, "일이") --
    callers must leave the original text unchanged in that case, never
    guess at a value."""
    total = 0
    section = 0
    current_digit: int | None = None
    for ch in run:
        if ch in _DIGIT_VALUES:
            if current_digit is not None:
                return None
            current_digit = _DIGIT_VALUES[ch]
        elif ch in _UNIT_VALUES:
            section += (current_digit if current_digit is not None else 1) * _UNIT_VALUES[ch]
            current_digit = None
        elif ch in _BIG_UNIT_VALUES:
            section += current_digit if current_digit is not None else 0
            section = section or 1
            total += section * _BIG_UNIT_VALUES[ch]
            section = 0
            current_digit = None
        else:
            return None
    section += current_digit if current_digit is not None else 0
    return total + section


def _is_unit_word(token: str) -> bool:
    lowered = token.lower()
    return any(lowered.startswith(prefix) for prefix in _UNIT_WORD_PREFIXES)


def normalize_korean_number_words(text: str) -> str:
    """Rewrites a Sino-Korean number-word token to digits only when the
    very next whitespace-separated token is a recognized dose/measurement
    unit word (e.g. "오 밀리그램" -> "5 밀리그램"). Every other token,
    including a bare number word with no such neighbor, is left exactly as
    it was -- see module docstring for why that's the safe default rather
    than a gap to close blindly."""
    tokens = text.split(" ")
    for i, token in enumerate(tokens):
        if not token or any(ch not in _NUMBER_CHARS for ch in token):
            continue
        if i + 1 >= len(tokens) or not _is_unit_word(tokens[i + 1]):
            continue
        value = _parse_sino_korean_number(token)
        if value is not None:
            tokens[i] = str(value)
    return " ".join(tokens)


def contains_number_word(text: str) -> bool:
    """True if `text` has an ASCII digit or at least one Sino-Korean
    number-word character (일/이/삼/.../백/천/만). A bare `\\d`-only check
    misses real ASR output that renders a spoken number as Hangul words
    instead of digits (tasks/06_ASR_OUTPUT_VERIFICATION.md's real
    "백사십오에구십이초금" example) -- callers that need this (mock
    provider vital-sign detection, enrichment_validation.py's grounding
    check) would otherwise silently clear/ignore a real number just
    because it wasn't spelled with digits.

    Deliberately loose (a single matching character anywhere, not the
    whole-token purity normalize_korean_number_words() requires) --
    callers use this only as "does some evidence of a number exist here",
    never to auto-apply a value, so an occasional false positive (an
    ordinary word that happens to contain one of these syllables) costs
    nothing once needs_review is forced True regardless."""
    return any(ch.isdigit() for ch in text) or any(ch in _NUMBER_CHARS for ch in text)

"""tasks/06_ASR_OUTPUT_VERIFICATION.md 선택지 B: 사전 기반 약명 fuzzy 교정.

asr_normalize.py의 숫자 정규화와 달리, 약명 교정은 "같은 값의 다른 표기"가
아니라 "ASR이 잘못 들은 걸 추측으로 고치는" 일이라 안전성이 다르다. 그래서
이 모듈은 절대 원문을 덮어쓰지 않는다 -- find_medication_candidates()는
텍스트를 그대로 두고, "이 구간이 사전의 이 약물과 비슷하다"는 후보만
반환한다. 후보를 그대로 신뢰해 자동 반영하면 CLAUDE.md의 "입력에 없는
약물을 생성하지 않는다"를 교정이라는 이름으로 어기는 셈이 된다 -- 후보는
검토 대상(needs_review)일 뿐, 확정값이 아니다.

유사도는 app.eval.asr_metrics.compute_cer로 계산한다(1 - CER, 0 이하는
0으로 자른다) -- 같은 편집거리 계산을 재사용해 새 알고리즘을 만들지 않는다.

Pure, no sherpa_onnx import -- unit-testable without real models (see
apps/api/tests/test_medication_candidates.py). 아직 어떤 ASRProvider나
파이프라인 단계에도 연결돼 있지 않다 -- tasks/06 참고.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.eval.asr_metrics import compute_cer

# 작게 시작한 큐레이션 목록 -- 실제 원내 처방 목록이나 공개 의약품 DB로
# 교체 가능하도록 `dictionary` 파라미터로 주입받는다(기본값일 뿐, 하드코딩
# 의존 아님). 이 프로젝트의 기존 합성 fixture(sample_consultation 등)와
# 흔한 1차 진료 약물을 섞어 담았다 -- 전체 약전이 아니라 데모/평가용 시작점.
DEFAULT_MEDICATION_DICTIONARY: tuple[str, ...] = (
    "리시노프릴", "아스피린", "메트포르민", "암로디핀", "아토르바스타틴",
    "와파린", "오메프라졸", "아목시실린", "클로피도그렐", "심바스타틴",
    "로사르탄", "푸로세미드", "메트로니다졸", "아세트아미노펜", "이부프로펜",
)


@dataclass
class MedicationNameCandidate:
    matched_span: str
    suggested_name: str
    similarity: float
    token_start_index: int
    token_end_index: int


def _similarity(a: str, b: str) -> float:
    rate = compute_cer(a, b).rate
    return max(0.0, 1.0 - rate)


def find_medication_candidates(
    text: str,
    dictionary: Sequence[str] = DEFAULT_MEDICATION_DICTIONARY,
    min_similarity: float = 0.6,
    window_sizes: tuple[int, ...] = (1, 2),
) -> list[MedicationNameCandidate]:
    """텍스트를 바꾸지 않는다 -- 사전 항목과 비슷한(min_similarity 이상)
    구간을 찾아 후보로만 반환한다. 이미 사전 항목과 정확히 같은 구간은
    후보로 내지 않는다(고칠 게 없음). 겹치는 window에서 여러 후보가 나오면
    유사도가 가장 높은 것만 남기고 나머지는 버린다(같은 구간을 중복 보고
    하지 않기 위함)."""
    tokens = text.split(" ")

    # Pass 1: any span that's an exact dictionary hit at any window size is
    # already correct -- protect its token range so a larger overlapping
    # window can't later "fuzzy correct" it anyway (e.g. "아스피린을" at
    # window=2 must not out-vote the exact window=1 match "아스피린").
    exact_match_indices: set[int] = set()
    for window in window_sizes:
        for i in range(len(tokens) - window + 1):
            span_tokens = tokens[i : i + window]
            if not all(span_tokens):
                continue
            if "".join(span_tokens) in dictionary:
                exact_match_indices.update(range(i, i + window))

    # Pass 2: fuzzy candidates, skipping any span that overlaps an exact match.
    raw_candidates: list[MedicationNameCandidate] = []
    for window in window_sizes:
        for i in range(len(tokens) - window + 1):
            if any(idx in exact_match_indices for idx in range(i, i + window)):
                continue
            span_tokens = tokens[i : i + window]
            if not all(span_tokens):
                continue
            span = "".join(span_tokens)
            best_name = None
            best_similarity = 0.0
            for name in dictionary:
                sim = _similarity(name, span)
                if sim > best_similarity:
                    best_similarity = sim
                    best_name = name
            if best_name is not None and best_similarity >= min_similarity:
                raw_candidates.append(
                    MedicationNameCandidate(
                        matched_span=span,
                        suggested_name=best_name,
                        similarity=round(best_similarity, 3),
                        token_start_index=i,
                        token_end_index=i + window,
                    )
                )

    raw_candidates.sort(key=lambda c: c.similarity, reverse=True)
    selected: list[MedicationNameCandidate] = []
    occupied: set[int] = set(exact_match_indices)
    for candidate in raw_candidates:
        span_range = range(candidate.token_start_index, candidate.token_end_index)
        if any(idx in occupied for idx in span_range):
            continue
        selected.append(candidate)
        occupied.update(span_range)

    selected.sort(key=lambda c: c.token_start_index)
    return selected

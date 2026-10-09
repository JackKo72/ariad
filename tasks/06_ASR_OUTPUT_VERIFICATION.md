# Task 06: ASR Output Verification + Post-ASR Correction Stage

## 배경 (사용자 요청, 2026-10-07)

tasks/05에서 ASR 정확도를 "4개 anchor(약명/용량/부정/날짜) PASS/FAIL"로만
검증해왔다. 사용자 요청(원문 취지): "다른 WER CER 등도 검증이 필요할거야.
검증하는 단을 만들어서, ASR 이후 어떤 제2의 단이 ASR 아웃풋을 좋게 만들지
고민해볼 수 있어? 현재 ASR 모델에서 진행해줘."

두 가지 요청으로 분리:
1. **검증 단 신설**: anchor 방식보다 촘촘한 정량 지표(WER/CER)로 ASR 출력을
   검증한다.
2. **제2의 단 설계**: ASR 이후에 출력을 개선하는 후처리 단계를 고민하고,
   **현재 기본 ASR 모델**(sherpa-onnx large-v3, CPU, ko_only — faster-whisper
   등 실험 중인 엔진이 아니라)을 대상으로 진행한다.

## 1. 검증 단 — WER/CER (실측 가능한 범위까지 구현 완료)

- `apps/api/app/eval/asr_metrics.py`(신규): 표준 편집거리(Levenshtein)
  기반 `compute_cer`/`compute_wer`. 기존 anchor 방식(네 구절만 PASS/FAIL)과
  달리 세그먼트 전체 문자/단어에 대해 S(대체)/D(삭제)/I(삽입)와 rate를
  계산한다. `aggregate()`로 세그먼트 전체를 micro-average(세그먼트별 rate의
  단순 평균이 아니라, 오류 수와 기준 길이를 각각 합산한 뒤 비율을 계산 —
  짧은 세그먼트가 긴 세그먼트와 동일한 가중치를 갖지 않도록)한다.
  `docs/TESTING_AND_EVALS.md`가 이미 "한국어는 WER보다 CER 우선"이라고
  명시하므로 CER을 주 지표로 유지하고 WER은 참고 지표로 함께 기록한다(한국어
  ASR 띄어쓰기가 일정하지 않아 WER 단독 판단은 신뢰하지 않음 — 기존 정책
  변경 없음, 지표 추가만).
- `scripts/compare_asr_accuracy.py`에 통합: 세그먼트별 CER/WER 출력 +
  전체 집계 CER/WER 출력을 기존 anchor 체크 앞에 추가. 기존 anchor 체크는
  그대로 유지(네 구절 PASS/FAIL은 "핵심 임상 정보가 살았는가"를 보는 용도로
  여전히 유효 — CER/WER은 그 anchor가 짚지 못하는 나머지 구간의 회귀까지
  잡는 용도).
- 단위 테스트: `apps/api/tests/test_asr_metrics.py`(13개) — 동일 텍스트,
  단일 대체/삭제/삽입, 공백 무시, 빈 문자열 경계, micro-average 검증.
- **이 샌드박스에는 sherpa-onnx 모델이 없어 실제 수치는 못 냈다** —
  `make compare-asr-accuracy`를 사용자 하드웨어에서 실행해야 실제 CER/WER
  숫자가 나온다.

## 2. 제2의 단 — 후처리로 ASR 출력을 개선하는 방법 고민

### 고려한 선택지와 트레이드오프

| 방식 | 안전성 | 커버리지 | 구현 난도 |
|---|---|---|---|
| **A. 결정적 텍스트 정규화**(예: 한글 숫자→아라비아 숫자) | 높음 — 입력에 있던 내용을 재표기만 함, 새 값을 지어내지 않음 | 좁음 — 규칙이 커버하는 패턴만 | 낮음 |
| B. 사전 기반 유사도 교정(약명/용어 fuzzy match) | 중간 — 교정 후보에 confidence 없이 덮어쓰면 위험, `needs_review`로 보내면 안전 | 중간 — 등록된 사전 범위만 | 중간 |
| C. LLM 기반 자유 교정("문맥상 이 말이 맞을 것이다") | **낮음** — CLAUDE.md가 금지하는 "입력에 없는 진단·약물·용량·수치·날짜 생성"을 할 위험이 구조적으로 존재 | 넓음 | 높음(+검증 비용) |

이번 범위는 **A만 구현**했다. B(사전 기반 교정)는 설계는 아래에 적되
구현하지 않았고, C(LLM 자유 교정)는 CLAUDE.md의 핵심 안전 규칙과 정면으로
충돌할 위험이 커서 **추천하지 않는다** — 하류에서 "근거 있는 교정"과
"그럴듯한 추측"을 구분할 방법이 없는 한 채택하면 안 된다.

### A. 구현: 한글 숫자 단어 → 숫자 정규화 (결정적, 안전)

`apps/api/app/pipeline/asr_normalize.py`(신규): `normalize_korean_number_words()`.

- **범위**: Sino-Korean 숫자 단어(일,이,삼...백,천,만)가 **바로 다음
  토큰이 투약 단위어(밀리그램/mg/정/캡슐/회/번 등)일 때만** 숫자로 치환한다
  (tasks/05에서 실제로 관찰된 "오 밀리그램" 패턴). 같은 음절로 시작하는
  일반 단어(감탄사 "오!", "사과", "이과", "이십대" 등)와 혼동하지 않도록,
  단위어가 바로 뒤에 없으면 절대 건드리지 않는다.
- **의도적으로 범위 밖에 둔 것**: 단위어 없이 단독으로 나온 숫자 표현(예:
  tasks/05의 "145에 92로" 혈압 수치 가르침 — "백사십오에 구십이로"). 단위어
  anchor 없이는 일반 단어와 구분할 안전한 방법이 없어서, 추측하지 않고
  그대로 둔다(기능 누락이지 버그가 아님 — 아래 "남은 위험" 참고).
- 입력에 없던 값을 지어내지 않는다 — "오"와 "5"는 같은 발화의 다른 표기일
  뿐, 새 수치를 추가하는 게 아니다(CLAUDE.md 금지 규칙은 "다른 값 발명"을
  막는 것이고, "같은 값의 표기 통일"은 해당하지 않는다고 판단).
- 단위 테스트: `apps/api/tests/test_asr_normalize.py`(17개) — 정상 케이스
  (오 밀리그램→5 밀리그램, 십오 mg→15 mg, 삼 회→3 회) + 안전성 케이스
  (감탄사 "오!" 안 건드림, "사과"/"이과"/"이십대" 안 건드림, 단위어 없는
  혈압 수치는 그대로 둠, 마지막 토큰이라 다음 단위어가 없는 경우 안 건드림).
- `scripts/compare_asr_accuracy.py`에 "정규화 전/후 CER·WER 비교"를
  추가했다 — **중요한 주의점**: `sample_consultation.transcript.json`의
  ground truth 자체가 투약량을 "오 밀리그램"(말한 그대로의 구어체)으로
  적어뒀다. 즉 ASR 출력을 숫자로 정규화하면 오히려 이 특정 fixture의
  ground truth 원문과는 **덜 비슷해 보일 수 있다**(텍스트 일치도가
  내려가도 의미는 더 정규화된 것 — 이 둘을 혼동하면 안 된다). 그래서
  비교는 "원문 vs 원문"이 아니라 "양쪽 다 정규화한 뒤 비교"로 설계했다 —
  ASR이 숫자/한글 중 어느 쪽으로 말했든 정규화 후에는 같은 표기로 수렴하는지
  보는 것이 이 단계의 실제 목적이다(구조화 단계가 용량을 안정적으로 추출할
  수 있게 하는 것 — ground truth 문자 일치율을 올리는 게 목적이 아님).
- **아직 production 파이프라인(`SherpaOnnxASRProvider`/`ParallelASRProvider`)
  에 연결하지 않았다** — 순수 함수로만 존재. 연결 여부는 사용자 하드웨어에서
  `make compare-asr-accuracy` 실측 후 판단하는 게 맞다고 본다(정규화가 실제
  구조화 단계의 용량 추출 정확도를 올리는지까지 확인해야 완전한 근거가 됨).

### B. 구현 완료: 사전 기반 약명 fuzzy 교정 (2026-10-07)

`apps/api/app/pipeline/medication_candidates.py`(신규):
`find_medication_candidates(text, dictionary=DEFAULT_MEDICATION_DICTIONARY,
min_similarity=0.6, window_sizes=(1,2))`.

- 약명 사전(현재 15개, 1차 진료 흔한 약물 + 기존 fixture 약물 — 전체
  약전이 아니라 시작점)을 `dictionary` 파라미터로 주입받는다(기본값일
  뿐, 원내 처방 목록이나 공개 의약품 DB로 교체 가능 — CLAUDE.md "provider
  의존성은 주입한다"와 같은 원칙).
- 유사도는 `app.eval.asr_metrics.compute_cer`를 재사용(1 - CER)해서 계산
  — 새 편집거리 알고리즘을 또 만들지 않았다.
- **원문을 절대 덮어쓰지 않는다** — 반환값은 `MedicationNameCandidate`
  (구간, 제안 약명, 유사도, 토큰 위치) 목록뿐이고, 호출자가 텍스트를
  바꾸는 어떤 함수도 이 모듈에 없다. 이미 사전과 정확히 일치하는 구간은
  "고칠 게 없음"으로 후보에서 제외한다.
- **실제 버그를 테스트 작성 중 직접 발견·수정**: window=2(토큰 2개 묶음)
  슬라이딩이 "아스피린을"(아스피린+을, 조사 포함)을 "아스피린"과만 비교해
  유사도 0.75로 오탐지하는 문제가 있었다 — window=1에서는 "아스피린"이
  이미 정확히 일치해서 후보가 아니었는데, 더 큰 window가 그 보호를 무시하고
  끼어든 것. 정확히 일치하는 구간(모든 window 크기 기준)을 먼저 전부
  찾아 "보호 구간"으로 선점한 뒤에 fuzzy 매칭을 돌리도록 고쳤다.
- 심한 garble(tasks/05의 "리시노프릴"→"리신 오프리오")은 유사도 ~0.2로
  기본 임계값(0.6)에 한참 못 미쳐 **정직하게 후보를 내지 않는다** — 이
  방식이 모든 garble을 못 잡는다는 걸 숨기지 않고 테스트로 명시했다.
- 단위 테스트: `apps/api/tests/test_medication_candidates.py`(8개) — 정확
  일치 무시, 경미한 오류 포착(유사도 0.8), 심한 오류는 정직하게 미포착,
  무관한 텍스트 빈 결과, 겹치는 window 중복 방지(버그 재발 방지 테스트),
  사전 주입, 임계값 적용, 위치순 정렬.
- `scripts/compare_asr_accuracy.py`에 "Medication name candidates
  (needs_review)" 출력 섹션 추가 — 어떤 교정도 적용하지 않고 후보만 보여줌.
- **아직 어디에도 연결 안 함** — 선택지 A(숫자 정규화)와 같은 이유로,
  production ASRProvider나 clinical_enrichment 단계에 자동 연결하지
  않았다. 후보를 누가/언제 검토하는지(UI 없음, Phase 04에서 이미 알려진
  제한)는 별도 결정 필요.

## 단위어 anchor 개념 — 질문에 대한 답 (2026-10-07)

사용자 질문: "혈압이라는 단어가 나오고 뒤에 나오는 숫자는 혈압일 것 —
이런 anchoring이 필요한 거지?"

맞다, 다만 방향이 반대다. 선택지 A가 쓴 anchor는 **숫자 뒤에 오는
단위어**(밀리그램/mg/회 등 — trailing anchor)였고, 사용자가 말한 건
**숫자 앞에 오는 도메인 키워드**(혈압/체중/혈당 — leading anchor)다.
둘 다 "숫자 자체만 보지 않고, 숫자가 실제로 수치임을 보장하는 주변 문맥이
있어야 정규화한다"는 같은 원칙의 다른 방향일 뿐이다.

leading anchor가 trailing anchor보다 어려운 이유:
1. **거리 문제**: "혈압을 재보니 145에 92로"처럼 키워드와 실제 숫자 사이에
   토큰이 여러 개 끼어 있다 — "다음 토큰" 체크로는 못 잡고, 몇 토큰까지
   허용할지 윈도우를 정해야 한다.
2. **소유권 모호성**: 같은 문장에 다른 수치가 섞이면("혈압도 좋은데 체중이
   92킬로그램이네요") "혈압" 근처의 숫자가 실제로는 체중일 수 있다 —
   trailing anchor(단위어 직접 인접)보다 오탐 위험이 구조적으로 더 크다.

**사용자의 "면담 몇 개를 ASR 해보면 패턴이 보일 것"이라는 제안이 맞는
접근**이라고 본다 — 단, CLAUDE.md("테스트에는 합성 데이터만 사용한다")
때문에 실제 환자 음성이 아니라 **합성 fixture를 몇 개 더 만들어서** 혈압/
체중/혈당/체온을 다양한 어순으로 말하는 패턴을 모아야 한다. 이건 이번
task 범위에 넣지 않았다 — 별도 작업으로 제안한다(다음 섹션).

### 제안하는 다음 단계 (미착수, 사용자 확인 필요)

1. `tests/fixtures/audio/`에 혈압/체중/혈당/체온 수치를 다양한 어순·화자
   패턴으로 말하는 합성 면담 fixture 2~3개 추가(TTS로 생성, 기존
   `scripts/generate_sample_audio.py` 방식 재사용).
2. 그 fixture들에 현재 기본 ASR 모델을 실제로 돌려(사용자 하드웨어에서,
   이 샌드박스는 모델이 없음) "숫자가 실제로 어떻게 깨지는지", "키워드와
   숫자 사이 거리가 보통 몇 토큰인지"를 관찰.
3. 관찰한 패턴을 바탕으로 leading-keyword anchor 규칙을 설계 — 소유권
   모호성 문제(위 2번)를 어떻게 처리할지는 이 관찰 없이는 추측에 불과하다.

## Out of scope (이번 task)

- LLM 기반 자유 교정 단계(선택지 C) — 구현하지 않음, 추천하지 않음.
- 정규화/교정 단계를 production ASRProvider에 기본 연결하는 것.
- `check_faster_whisper_accuracy.py`에 동일 CER/WER 통합(사용자가 "현재 ASR
  모델"로 범위를 한정했으므로 faster-whisper 실험 경로는 건너뜀).
- leading-keyword anchor(혈압/체중 등) 설계·구현 — 위 "제안하는 다음 단계"
  참고, 합성 fixture로 패턴을 먼저 관찰해야 한다.

## 남은 위험

- 단위어 anchor가 없는 숫자 표현(혈압/검사수치 등)은 이번 정규화로 전혀
  개선되지 않는다 — leading-keyword anchor 설계 필요, 미확정(위 참고).
- CER/WER 실측값이 아직 하나도 없다(GPU/모델 없는 샌드박스의 구조적 한계) —
  `make compare-asr-accuracy` 실행 전까지는 "검증 단이 생겼다"는 것만 사실,
  "현재 ASR 모델의 실제 CER/WER가 얼마인가"는 미확정.
- 정규화 함수의 단위어 목록(`_UNIT_WORD_PREFIXES`)이 좁아서, 날짜 단위
  (월/일/년)나 다른 임상 수치 패턴은 아직 커버하지 않는다 — 의도적 범위
  제한이지만, 사용자가 범위를 넓히고 싶다면 추가 작업 필요.
- 약명 사전(`DEFAULT_MEDICATION_DICTIONARY`)이 15개뿐이라 커버리지가
  좁다 — 실측(사용자 하드웨어) 후 자주 등장하는데 못 잡는 약물이 보이면
  사전을 늘려야 한다. 사전에 없는 약물은 구조적으로 교정 후보가 안 나온다.
- 유사도 임계값(0.6)과 사전 범위 모두 아직 실측 없이 정한 값이다 —
  `make compare-asr-accuracy` 실측 후 오탐/누락 비율을 보고 조정 필요.

## 사용자 첫 실측 결과 분석 + 검증 단 버그 수정 (2026-10-07)

사용자가 `make compare-asr-accuracy`(sample_consultation.wav, 59.54s)를
실제 하드웨어에서 돌린 결과를 보내왔다.

### 발견한 버그: per-segment CER/WER가 전부 터무니없는 값(2.5~88.5)

**원인**: 이 fixture는 README에 이미 기록된 알려진 제한 때문에, 화자분리가
10개 gt 세그먼트를 전부 **단 1개의 병합된 segment**로 반환한다. 내가 만든
`_match_predicted_text`는 시간 겹침으로 매칭하므로, 이 1개 segment가
0~59.54초 전체와 겹쳐서 **모든 gt 세그먼트가 같은 전체 전사문 덩어리와
매칭**된다. 그 상태에서 짧은 gt 세그먼트(예: 6글자 "알겠습니다")를
500자가 넘는 전체 전사문과 편집거리로 비교하니 CER이 88.5처럼 1을 훌쩍
넘는 값이 나왔다 — 숫자 자체가 무의미했다(anchor 체크는 부분문자열
포함 여부만 보므로 이 문제에 영향받지 않아 그대로 유효했다).

**수정**: `scripts/compare_asr_accuracy.py`에 **전체 전사문 기준
CER/WER**(gt 세그먼트를 순서대로 합친 문자열 vs 실제 predicted_segments를
순서대로 합친 문자열 — 세그먼트 개수가 안 맞아도 항상 올바름)을 추가해
이걸 "믿을 수 있는 숫자"로 표시하도록 바꿨다. `predicted_segments` 개수가
`ground_truth`보다 적으면("화자분리가 병합했을 가능성") 경고를 출력하고,
그럴 때 per-segment 숫자 옆에 "의미 없음" 표시를 붙인다. 정규화 전/후
비교도 전체 전사문 기준으로 다시 맞췄다. 수정 후 실제로 사용자가 보낸
ko_only 출력을 재계산해보니 **전체 전사문 CER 0.542, WER 0.662**로
합리적인 범위가 나왔다(이 숫자는 이 샌드박스에서 사후 재계산한 것이고,
사용자 하드웨어에서 수정된 스크립트로 다시 돌려야 공식 수치가 된다).

### 실측 내용 자체에서 읻은 것 (tasks/05 기존 발견과 일치)

- `auto_then_ko`: RTF 2.82, 완전히 깨진 라틴 음차 환각("Annion haseo!
  Odul fiora...") — tasks/05에서 이미 확인된 실패 패턴 재현.
- `ko_only`(현재 기본값): RTF 1.37, 읽을 수 있는 한국어. 부정 표현
  "시작하지 않습니다" **보존**(anchor PASS) — 기존 발견과 일치. 약명/용량/
  날짜 anchor는 모두 FAIL — "리시노프릴"→"약리신", "오 밀리그램"→
  "오오 밀크 레"(tasks/05에서 봤던 것과 **동일한 깨짐 패턴**, 재현성 확인).
- **"145에 92로"(혈압)가 실제로 어떻게 깨지는지 처음 확인**: "백사십오에
  구십이초금"으로 — 숫자 두 개가 하나로 붙어버리고 "로"가 다음 단어
  "조금"과 섞여 "초금"이 됐다. 이건 내가 테스트에 쓴 깨끗한 예시
  ("백사십오에 구십이로")보다 훨씬 지저분하다 — 토큰 경계 자체가
  깨져서, leading-keyword anchor를 설계해도 "숫자 뒤에 특정 조사가 온다"는
  가정이 이 경우엔 안 맞는다. 이 발견이 아래 vital-signs fixture와
  leading-anchor 설계를 더 보수적으로 접근해야 하는 이유다.
- diarization은 여전히 10개 세그먼트를 1개로 병합(README의 기존 알려진
  제한, 이번에 다시 확인됨) — 이번 task 범위 밖(Phase 2 과제).

## 리딩 앵커 연구용 합성 fixture 추가 (2026-10-07)

사용자 제안("면담 몇 개를 ASR 해보면 패턴이 보일 것")에 따라, 실제 환자
음성 대신(CLAUDE.md) **합성 fixture**를 새로 만들었다:

- `scripts/generate_vital_signs_fixture.py`(신규, `make vital-signs-audio`)
  — `generate_sample_audio.py`와 같은 방식(espeak-ng+ffmpeg)으로
  `tests/fixtures/audio/vital_signs_dictation.wav`(53.3s, 12 세그먼트) +
  `.transcript.json` 생성. 이 샌드박스에 espeak-ng/ffmpeg가 있어서 직접
  생성·검증(ffprobe로 duration/포맷 확인)까지 완료했다 — 실제 ASR 실행은
  여전히 사용자 하드웨어에서 필요.
- 담은 패턴(각 세그먼트에 `vital_sign_pattern` 메타데이터로 표시):
  1. **혈압, bare number, leading keyword만**(단위어 없음) — "혈압을
     재보니 138에 86으로"
  2. **체중, leading + trailing anchor 둘 다**("체중을 확인해보니
     72킬로그램이네요") — trailing anchor 규칙이 이미 처리 가능한지 확인
  3. **혈당, 키워드와 숫자가 멀리 떨어짐**("공복 혈당 검사를 했는데
     수치가 118로") — 거리 문제 실측용
  4. **맥박, trailing unit이지만 중간에 단어가 끼어 있음**("맥박은 분당
     76회로") — "분당"이 숫자와 단위어 사이에 끼어든 경우
  5. **한 문장에 두 생체 수치**("혈압이 132에 84, 맥박은 70회였습니다")
     — 소유권 모호성(어떤 숫자가 어떤 키워드에 속하는지) 실측용
  6. **소수점 체온**("체온을 재보니 37.5도였습니다") — 현재 정규화기
     범위 밖임을 알고 포함, ASR이 소수점을 어떻게 다루는지만 관찰
- `scripts/compare_asr_accuracy.py`도 이 fixture에 맞게 보강: 다른
  ground truth 파일을 쓸 때(`GROUND_TRUTH=` 오버라이드) 거기 없는
  anchor 체크는 FAIL이 아니라 `[SKIPPED] (not in this ground truth file)`
  로 표시하도록 고쳤다(기존 4개 anchor는 sample_consultation 전용이므로
  이 새 fixture에선 전부 적용 불가 — 혼란스러운 거짓 FAIL을 막기 위함).

**사용자가 직접 실행할 것**:
```bash
AUDIO=tests/fixtures/audio/vital_signs_dictation.wav \
GROUND_TRUTH=tests/fixtures/audio/vital_signs_dictation.transcript.json \
make compare-asr-accuracy
```
결과(특히 whole-transcript 비교의 predicted 텍스트)를 보면 숫자-키워드
거리, 소유권 모호성, 소수점 처리가 실제로 어떻게 깨지는지 보일 것이다 —
그걸 보고 나서 leading-keyword anchor 규칙을 설계하는 게 맞다(지금
추측으로 설계하면 위 "145/92" 사례처럼 토큰 경계 가정이 틀릴 위험이 크다).

## Out of scope 추가

- leading-keyword anchor 규칙 자체의 설계/구현 — vital-signs fixture
  실측 결과를 받은 뒤 진행.
- diarization이 10개 세그먼트를 1개로 병합하는 근본 문제 수정 — 별도
  과제(tasks/03 Phase 2 전제조건으로 이미 기록됨).

## vital-signs fixture 실측 결과 — 숫자가 "깨짐"이 아니라 "소실" (2026-10-09)

사용자가 `vital_signs_dictation.wav`로 `make compare-asr-accuracy`를
실행한 결과를 보냈다. **leading-keyword anchor 설계보다 먼저 다뤄야 할
더 근본적인 문제를 발견했다.**

### 발견 1: 숫자 5개(138/86, 72, 118, 76, 132/84/70)가 전부 사라짐

ko_only(현재 기본값) 전체 전사문에서 숫자가 포함된 6개 문장(도입부
혈압/체중/혈당/맥박/혈압·맥박 동시/체온) 전부, **숫자 자체가 아예
나타나지 않았다** — 숫자 아닌 음절로 대체되거나 그냥 사라졌다:

| 기대 | 실제 predicted |
|---|---|
| "혈압을 재보니 138에 86으로 나왔습니다" | "여러 불한 일상 속에 빠어 유가 니다" |
| "체중을 확인해보니 72킬로그램이네요" | "해율과 인해니 실시피크이도 구요" |
| "검사를 했는데 수치가 118로 나왔습니다" | "돈 복단 점사 스치카스입 파 니다" |

반면 숫자가 없는 짧은 환자 대답은 정확하거나 거의 정확했다("네,
알겠습니다." → 완전 일치, "지난번보다 조금 높아진 것 같아요." →
"지다 조금 높아진 것 같아요."). **이건 tasks/05의 "145에 92로" →
"백사십오에구십이초금"보다 더 나쁜 결과다** — 그때는 숫자 음절이 깨진
채로라도 남아있었는데, 이번엔 숫자 음절 자체가 하나도 안 보인다.

### 발견 2: TTS 발음 문제가 아님을 직접 확인함

이 샌드박스에서 `espeak-ng -v ko -x`(음소 출력, 오디오 재생 없이 텍스트만
확인 가능)로 직접 확인:

```
espeak-ng -v ko -x "138에 86으로"   ->  백(100)+삼(3)+십(10)+팔(8) 에 팔(8)+십(10)+육(6) 으로
espeak-ng -v ko -x "72킬로그램"      ->  칠(7)+십(10)+이(2) 킬로그램
espeak-ng -v ko -x "145에 92로"      ->  백(100)+사(4)+십(10)+오(5) 에 구(9)+십(10)+이(2) 로
```

전부 올바른 한국어 숫자 단어로 정확히 발음된다. **TTS가 숫자를 잘못
읽어서 ASR이 못 알아들은 게 아니다** — 오디오 자체는 "백삼십팔...
팔십육..."을 정확히 말하고 있는데, ASR이 그걸 인식하지 못하고 전혀 다른
음절을 뱉어낸 것이다.

### 가설(코드로 근거는 있지만 확정은 아님): 디코딩 구간 길이

`SherpaOnnxASRProvider.merge_diarization_turns()`는 병합된 구간이
28초(`max_segment_seconds`)를 넘으면 균등 분할한다. 이 프로젝트의 알려진
diarization 병합 버그(README) 때문에 두 fixture 모두 전체가 먼저 1개
구간으로 뭉쳐지는데:

- `sample_consultation.wav`(59.54s) → ceil(59.54/28)=**3조각**(~19.9s씩)
  → 숫자 1개 사례, **깨졌지만 숫자 음절은 남음**
- `vital_signs_dictation.wav`(53.34s) → ceil(53.34/28)=**2조각**(~26.7s씩)
  → 숫자 5개 사례, **전부 소실**

조각이 길수록(26.7s > 19.9s) 숫자 인식이 더 나빠지는 상관관계가 보이지만,
**표본이 2개뿐이라 증명은 아니다** — 추측을 사실처럼 말하지 않기 위해
검증용 fixture를 추가로 만들었다(아래).

### 별개로 확인한 것: auto_then_ko ≈ ko_only RTF (2.35 = 2.35, 평소엔 2x 차이였음)

`_NON_KOREAN_RE = re.compile(r"[Ͱ-ϿЀ-ӿ؀-ۿ぀-ヿ一-鿿]")`(그리스/키릴/아랍/
일본어가나/CJK만 매치, **라틴 문자는 매치 안 함**)를 코드에서 직접
재확인했다. auto_then_ko의 자체 auto-decode 결과가 라틴 문자로만 된
환각("Oul fiora pulce...", 심지어 헝가리어 단어 "és ez a nyúl"까지 섞임)
이라서, `ko_fired = _NON_KOREAN_RE.search(text) or turn_duration < 1.2`가
**False**가 되어 이번엔 ko fallback 디코딩이 전혀 안 일어난 것으로
보인다 — 그래서 auto_then_ko도 이번엔 디코딩을 1회만 해서(auto만) ko_only
(ko만 1회)와 시간이 비슷해진 것 같다. sample_consultation에서는 같은
라틴 환각이었는데도 auto_then_ko가 ko_only의 2배였던 것과 대조적인데,
그건 그 fixture가 3조각으로 나뉘어서 조각마다 ko_fired 여부가 달랐을
가능성이 있다(모든 조각이 라틴 환각이 아니었을 수 있음) — 역시 추측,
`make diagnose-asr`로 조각별 `ko_fallback_count`를 보면 확인 가능하다.

### 다음 진단: `vital_signs_isolated.wav`(짧게 격리된 구간으로 재시험)

`scripts/generate_vital_signs_isolated_fixture.py`(신규,
`make vital-signs-isolated-audio`) — 숫자가 들어간 6개 문장만, **각 문장
사이에 2.0초 간격**(기존 fixture의 0.6초보다 길게, `merge_diarization_
turns`의 `merge_gap_seconds=0.8`보다 길게)을 둬서 화자 클러스터링이
틀려도 시간 간격만으로 병합이 막히도록 설계했다 — 각 문장이 자기만의
짧은(4~7초) 구간으로 디코딩될 것으로 예상된다(diarization이 실제로
6개 구간으로 나누는지는 `make diagnose-asr`로 확인 필요 — 간격 기반
방어가 클러스터링 버그보다 강한지는 아직 실측 전).

**사용자가 직접 실행할 것**:
```bash
AUDIO=tests/fixtures/audio/vital_signs_isolated.wav \
GROUND_TRUTH=tests/fixtures/audio/vital_signs_isolated.transcript.json \
make compare-asr-accuracy

# 추가로 실제 구간 개수/경계 확인:
make diagnose-asr AUDIO=tests/fixtures/audio/vital_signs_isolated.wav
```

**결과 해석 방법**:
- 숫자가 **돌아오면** → 디코딩 구간이 짧을수록 숫자 인식이 낫다는 뜻 —
  tasks/05 item 3의 미착수 후보("화자분리 전 발화 chunk 인식")가 숫자
  보존에도 도움될 근거가 되고, leading-keyword anchor 설계를 재개할 수
  있다(그때는 적어도 앵커를 걸 숫자 텍스트가 ASR 출력에 존재하니까).
- 숫자가 **여전히 안 돌아오면** → 구간 길이와 무관한 문제(이 양자화
  모델의 숫자 인식 자체 한계일 가능성) — leading-keyword anchor 설계는
  의미가 없다(앵커를 걸 대상 텍스트가 ASR 출력에 없으므로). 이 경우
  faster-whisper(CUDA, tasks/05 경로 A)로 같은 fixture를 돌려 다른
  런타임/정밀도에서도 같은 현상이 나는지 확인하는 게 다음 단계가 될 것.

**leading-keyword anchor 설계는 이 결과가 나올 때까지 보류한다** — 숫자
텍스트가 ASR 출력에 없는 상태에서 "앵커 규칙"을 설계하는 건 의미가 없다.

## `vital_signs_isolated.wav` 실측 결과 — 부분 개선, 가설 부분 반증 (2026-10-09)

`make diagnose-asr`가 실제로 **6개 구간을 따로 디코딩**했음을 확인시켜줬다
(2.0초 간격이 `merge_diarization_turns`의 0.8초 병합 임계값을 성공적으로
이겼다는 뜻):

```
turn  duration_s   ko_fired     ko_ms
0     5.906        True         13429.7
1     4.050        True         13773.7
2     5.754        True         14849.3
3     4.792        True         12992.5
4     6.986        True         15893.5
5     4.219        True          8637.7
```

**결과는 "완전 반증"도 "완전 확인"도 아니다 — 부분적으로만 개선됐다.**
짧게 격리된 구간에서도 숫자 6개 중 다수(138/86, 72, 118)는 여전히
완전히 사라졌다. 하지만 이번엔 숫자 조각이 **처음으로 일부 등장**했다 —
"팔십사"(84, seg_005의 "132에 84" 중 84 — **정확히 맞음**), "십 회"(seg_005
"70회였습니다" 중 단위 구조는 맞지만 값은 틀림), "삼십"(seg_006 "37.5도"의
"37" 일부 — 소수점·단위 소실). 긴 병합 구간(53.34초 전체가 2조각)에서는
숫자 음절이 **하나도** 안 나왔던 것과 비교하면, 짧은 구간(개별 4~7초)이
일부 숫자를 복구하긴 했다 — 즉 디코딩 구간 길이가 **원인 중 하나이긴
하지만 유일한 원인은 아니다.** 나머지 소실(138/86/72/118)은 구간을
짧게 해도 안 고쳐지는, 더 근본적인(양자화? 모델 자체?) 문제로 보인다.

**속도는 개선되지 않았다**: `diagnose-asr`의 `ko_fallback` 총
79576.5ms/31.71s 입력 = 순수 decode RTF **2.51** — 오히려 이전(merged,
긴 구간)보다 나쁘거나 비슷하다. 짧게 쪼개는 게 속도 이득은 없다 —
있다면 정확도 이득뿐인데, 그마저 부분적이다.

**별개로 확인한 것**: 이 fixture는 전부 의사(A) 화자만 담아서
"speaker/diarization consistency: 6/6(100%)"가 나왔는데, 이건 비교
대상이 전부 같은 라벨이라 trivially 100%인 것 — 화자분리 자체가
좋아졌다는 뜻은 아니다(설계상 이 fixture는 화자 구분을 테스트하지
않음). `auto_then_ko` vs `ko_only` RTF가 이번에도 비슷했다(2.12 vs
1.96) — 지난번과 같은 이유(`_NON_KOREAN_RE`가 라틴 문자를 못 잡아서
ko fallback이 안 일어남)로 재확인됨, 이 설명이 반복 재현된다는 뜻.

### 다음 진단: faster-whisper(다른 런타임/정밀도)로 같은 fixture 교차 확인

숫자 소실이 구간 길이와 무관하게 일부 남는다는 건, sherpa-onnx CPU int8
large-v3 양자화 모델 자체의 한계일 가능성을 시사한다. 이를 가르기 위해
**새 코드 없이 기존 도구로** 바로 확인 가능하다 —
`scripts/check_faster_whisper_accuracy.py`는 faster-whisper가 자체
세그먼트 경계를 쓰므로(diarization/merge_diarization_turns 영향을 전혀
안 받음) sherpa-onnx의 청크 분할 로직과 완전히 독립적으로 같은 질문을
던질 수 있다. `AUDIO=`/`GROUND_TRUTH=` 오버라이드도 이미 지원한다
(오늘 사용 중 발견: 이 스크립트도 `compare_asr_accuracy.py`와 같은 "다른
ground truth 파일의 미해당 anchor는 FAIL이 아니라 SKIPPED로 표시" 버그가
있어서 같이 고쳤다).

**사용자가 직접 실행할 것**:
```bash
FASTER_WHISPER_MODEL=large-v3 \
AUDIO=tests/fixtures/audio/vital_signs_isolated.wav \
GROUND_TRUTH=tests/fixtures/audio/vital_signs_isolated.transcript.json \
make check-faster-whisper-accuracy
```
(약명/부정/날짜 anchor 4개는 이 fixture에 없어 전부 SKIPPED로 나올 것 —
정상. 중요한 건 per-segment expected/predicted 텍스트에 숫자가 보이는지다.)

**결과 해석**:
- faster-whisper(CUDA, large-v3)에서 숫자가 **잘 나오면** → sherpa-onnx
  CPU int8 양자화 특유의 문제일 가능성이 커진다 — 다만 tasks/05에서
  이미 faster-whisper large-v3가 부정 표현("않")을 삭제하는 별도 안전
  문제가 확인됐으므로, "숫자는 되는데 부정은 안 되는" 트레이드오프를
  어떻게 다룰지 결정이 필요해진다.
- faster-whisper에서도 숫자가 **마찬가지로 빠지면** → 모델/엔진에
  무관하게 자연스러운 문장에 섞인 한국어 숫자 인식 자체가 현재 ASR
  스택 공통의 약점이라는 뜻 — 이 경우 post-ASR 텍스트 보정(leading/
  trailing anchor 등)으로는 해결할 수 없다(없는 텍스트를 보정할 수
  없음). 그 경우의 현실적인 다음 전략은 "숫자가 포함된 생체 신호
  필드는 ASR 결과를 신뢰하지 않고 항상 `needs_review`로 보낸다"는
  하류 안전장치 쪽으로 방향을 바꾸는 것이 될 것이다(CLAUDE.md의
  "불확실한 임상 사실은 검토 필요 상태로 보낸다" 원칙과 직접 부합).

**leading-keyword anchor 설계는 여전히 보류** — 위 교차 확인 결과가
나온 뒤, "post-ASR 보정으로 해결 가능한 문제인지" 자체를 먼저 판단해야
한다.

## 교차 확인 결과 — faster-whisper가 숫자를 거의 다 복구함 (2026-10-09)

사용자가 `FASTER_WHISPER_MODEL=large-v3`로 같은 `vital_signs_isolated.wav`
를 돌린 결과, **질문에 명확한 답이 나왔다**: 숫자 소실은 Whisper/한국어
숫자 인식 자체의 근본 한계가 아니라 **sherpa-onnx의 CPU int8 양자화
경로 특유의 문제**였다.

| 구간 | 기대 | sherpa-onnx(CPU int8, 격리) | faster-whisper(CUDA fp16, large-v3) |
|---|---|---|---|
| 138/86 | 백삼십팔에 팔십육으로 | (완전 소실) | "백삼 씹 파레팔 씹 유크로" — **백/삼/십/팔 + 십/육 전부 등장**(십→씹 오철자) |
| 72 | 칠십이 | (완전 소실) | "칠 씹 이" — **정확히 칠/십/이**(씹=십) |
| 118 | 백십팔 | (완전 소실) | "씹 파로" — 부분적(백 소실, 나머지 흔적) |
| 76 | 칠십육 | (완전 소실) | "칠 씹" — 부분적 |
| 132/84 | 백삼십이에 팔십사 | "팔십사"만 등장 | "백삼 씹 이에팔 씹사" — **거의 완벽**(백/삼/십/이/에/팔/십/사 전부) |
| 37.5 | 삼십칠점오도 | "삼십"만 등장 | "삼 씹 칠 오도" — **삼/십/칠 + 오도**(점은 소실, 숫자 둘 다 보존) |

**흥미로운 일관된 오류**: "십"이 거의 매번 "씹"으로 나온다(음이 비슷한
다른 한국어 단어로 대체됨) — 숫자 자체가 사라지는 게 아니라 한 음절이
동음이의어 비슷한 다른 글자로 바뀌는 수준의 오류다. sherpa-onnx의
"완전 소실"과는 질적으로 다르다.

**anchor 체크 "0/3 pass"는 의미 없는 신호다** — 주의할 점: 이 fixture는
`seg_003`/`seg_005`라는 segment id를 sample_consultation과 우연히
공유하지만 내용은 전혀 다르다(혈당/혈압 수치 문장이지 약명·부정 표현이
아님). 내가 고친 "SKIPPED" 처리는 **segment id가 ground truth에 없을
때만** 작동하므로, 이번처럼 id는 있지만 내용이 다른 경우는 걸러지지
않고 당연히 FAIL이 찍힌다(애초에 "리시노프릴"이 이 문장에 없으니까).
혼란의 여지가 있어 짚어둔다 — **실제로 봐야 할 신호는 anchor pass
개수가 아니라 위 표의 숫자 복구 여부다.**

### 결론: 엔진 교체가 아니라 트레이드오프 문제

faster-whisper(CUDA, large-v3)가 숫자 복구에는 훨씬 낫지만, tasks/05에서
**이미 확인된 별개의 안전 문제**가 있다 — 부정 표현("시작하지 않습니다")의
"않"이 통째로 사라지는 사례. 이 두 발견을 합치면:

| | 숫자 복구 | 부정 표현 보존 |
|---|---|---|
| 현재 기본(sherpa-onnx CPU int8) | 나쁨(거의 소실) | 좋음(보존) |
| faster-whisper CUDA large-v3 | 좋음(대부분 복구) | **나쁨(소실 확인됨)** |

**부정 표현 소실("중단하지 마세요"가 사라지는 것)이 숫자 소실보다 임상적
으로 더 위험하다** — 잘못된 혈압 수치는 의료진이 재확인하면 그치지만,
약물 중단/계속 지시가 반대로 읽히면 직접적 위해로 이어질 수 있다. 그래서
**이번 발견이 엔진 교체를 정당화하지는 않는다** — 오히려 "숫자든 부정이든
ASR 출력을 그대로 신뢰하지 않는다"는 쪽으로 결론이 기운다.

**post-ASR 텍스트 보정(leading/trailing anchor 등)은 여전히 설계하지
않는다** — sherpa-onnx 기본 경로에서는 숫자 텍스트가 대부분 없어서
보정할 대상이 없고, faster-whisper로 바꾸면 숫자는 있지만 부정 표현
문제가 새로 생긴다. 어느 쪽이든 "텍스트 패턴으로 고치기"보다 "신뢰하지
않고 검토로 보낸다"가 더 안전한 결론이다.

### 제안하는 다음 방향 (선택 필요 — 구현 전 확인)

1. **(낮은 리스크, 추천) 두 엔진 모두에서 숫자/수치 필드는 항상
   `needs_review`로 보낸다** — 어느 엔진을 쓰든 숫자 추출을 자동 신뢰하지
   않는다. 지금 바로 적용 가능하고(엔진 교체 불필요), CLAUDE.md의
   "불확실한 임상 사실은 검토 필요 상태로 보낸다" 원칙과 정확히 부합한다.
   `apps/api/app/pipeline/enrichment_validation.py`의 기존 숫자 관련
   검사를 확장하는 선에서 구현 가능해 보인다.
2. **(중간 리스크) faster-whisper의 부정 표현 소실 자체를 먼저 고친다**
   (예: 부정 조사/어미 패턴이 포함된 구간만 sherpa-onnx로 재확인하는
   하이브리드, 또는 dictionary 기반 "않"-포함 어미 사전과 비교) — 이게
   성공하면 faster-whisper의 숫자 복구 이점을 안전하게 가져올 길이
   열린다. 구현 난도와 검증 비용이 크다.
3. 둘 다 당장 보류하고 여기서 tasks/06을 정리 — 사용자가 이미 충분한
   실측을 얻었다고 판단하면.

**추천은 1번이다** — 당장 구현 가능하고 리스크가 낮으며, 어느 엔진을
최종 선택하든(또는 둘 다 안 바꾸든) 유효하다. 2번은 가치 있지만 별도
task로 분리할 만큼 크다. 어느 방향으로 진행할지 알려주면 이어서
진행하겠다.

## 1번 구현 완료: 숫자/수치 필드 강제 needs_review (2026-10-09)

사용자가 1번(엔진 교체 없이, 숫자/수치 필드를 항상 검토 필요로 보낸다)을
선택해 구현했다.

- `apps/api/app/domain/models.py`: `ExamFinding`에 `value_candidates:
  list[NormalizedCandidate]` 신규 필드 추가 — 기존 `score_candidates`
  (mRS/NIHSS/MRC 등 등급 전용)와 별도로, 혈압/체중/혈당/맥박/체온 같은
  **일반 수치 관찰**을 담는다. `score_candidates`의 기존 설계(원문에
  숫자가 그대로 있을 때만 채움)를 그대로 일반화한 것 — 새 패턴을 만들지
  않고 기존 메커니즘을 재사용했다.
- `apps/api/app/pipeline/enrichment_validation.py`: 두 가지 강제 규칙
  추가.
  1. **grounding 확장**: `value_candidates`도 `score_candidates`와 같은
     방식으로 source_span에 숫자가 실제로 있는지 검사하고, 없으면
     비운다(+ violation 기록).
  2. **신규: 무조건 `needs_review=True` 강제** — `MedicationFinding.
     dose_candidates`가 비어있지 않거나, `ExamFinding.score_candidates`/
     `value_candidates`가 비어있지 않으면(grounding 통과분만), provider가
     `needs_review=False`를 줬더라도 **무조건 `True`로 덮어쓴다**. 이게
     이번 요청의 핵심 — "어느 엔진을 쓰든" 숫자가 있으면 검토 필요를
     보장하는 지점이다(provider가 뭘 주든 이 레이어에서 강제).
- `prompts/clinical_enrichment.md`: `value_candidates`와 `dose_candidates`
  관련 안내 추가 — 모델이 `needs_review`를 낮추려 해도 시스템이 무시한다는
  점을 명시(실제 LLM provider가 이 규칙에 맞춰 불필요한 확신을 표현하지
  않도록).
- 테스트(`apps/api/tests/test_enrichment_validation.py`, 6개 추가):
  - `value_candidates` grounding 통과/실패 각각.
  - **provider가 명시적으로 `needs_review=False`를 줘도** 숫자 후보가
    있으면(exam value, medication dose 각각) 강제로 `True`가 되는지.
  - **역방향 확인**: 숫자 후보가 전혀 없는 medication은 provider가 준
    `needs_review=False`가 그대로 유지되는지(과잉 강제 없음 확인).
- `apps/api/app/providers/mock.py`는 수정하지 않았다 — mock은 아직
  `value_candidates`를 채우는 규칙이 없어서(혈압/체중 등 수치 관찰을
  감지하는 규칙 자체가 미구현) 이 변경의 영향을 받지 않는다. 실제 수치를
  추출하는 새 규칙(leading-keyword anchor 포함)은 여전히 보류 상태다 —
  이번 변경은 "추출된 숫자를 신뢰하지 않는다"는 안전장치이고, "숫자를
  더 잘 추출한다"는 별개의(아직 하지 않은) 작업이다.
- `apps/api/app/providers/openai_llm.py`는 수정 불필요 — `ClinicalEnrichment`
  pydantic 모델을 그대로 structured output 스키마로 쓰므로 새 필드가
  자동으로 반영된다.
- 전체 테스트 222개 통과(기존 217 + 신규 6 — 1개는 "과잉 강제 없음"
  역방향 테스트), ruff clean.

**의도적으로 하지 않은 것**: 실제 혈압/체중/혈당 수치를 ASR 텍스트에서
추출하는 규칙(leading-keyword anchor, mock provider 규칙 추가 등)은
여전히 미구현 — 이번 변경은 "있다면 믿지 않는다"이지 "더 잘 뽑아낸다"가
아니다. 프론트엔드에 이 `needs_review`/`value_candidates`를 보여주는
UI도 없음(Phase 04 때부터 알려진 제한, 그대로 유지).

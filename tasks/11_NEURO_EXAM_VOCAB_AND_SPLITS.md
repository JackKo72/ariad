# Task 11: 신경학적 진찰 공통 어휘 + 신경과 진료 틀 확장 + gpt-4o 기본 + 어휘용/평가용 분리

## 배경 (사용자 요청, 2026-10-10)

- 신경학적 진찰 전반(복시, spine 검사, 보행 검사 등)과 신경과 질환 전반을 다루고 싶다.
- 어휘 중 "용어 목록"은 지금 추가한다. "실제 말하는 방식"은 앞으로 녹음에서 보강한다.
- tasks/10의 REPEAT=3 실측에서 gpt-4o가 gpt-4o-mini보다 recall이 13~17%p 높았고
  (ER 64% vs 47%, ICU 72% vs 59%), 속도는 비슷했다. 그래서 기본 모델을 gpt-4o로 바꾼다.

## 구현

1. `prompts/frames/shared/neuro_exam.json`: 공통 신경학적 진찰 어휘 59개.
   - 의식·인지, 언어·말, 뇌신경(복시, 안진, 안면마비, 삼킴 등), 운동(근력, 회내 표류,
     강직, 진전 등), 반사(심부건반사, Babinski, Hoffmann, clonus), 감각, 협조
   - 보행(보행 검사, 일자 보행, Romberg, 발뒤꿈치·발끝 보행), 척추·수막(SLR, Spurling,
     압통, 경부강직, 배뇨·배변), 기본 검사(뇌 MRI, EEG, 요추천자, EMG/NCS, 경동맥
     초음파, 신경심리검사)
   - 규칙: 진찰 지시만 있고 결과를 말하지 않았으면 결과를 만들지 않는다. 등급·점수·
     좌우는 원문에 있을 때만 쓴다.
2. 진료 틀 9개. 모두 `"includes": ["neuro_exam"]`로 공통 진찰 어휘를 포함한다.
   - `general_neuro`(공통 진찰만), `stroke`, `seizure`(전조, 발작 후 상태, 전신·국소
     발작 의심, 혀 깨물림·실금, 비디오 뇌파 추가)
   - `headache`, `dizziness`, `movement`, `cognitive`, `neuromuscular`, `spine` (각 5~7개)
   - aphasia는 stroke에서 공통 진찰 어휘로 옮겼다.
3. `load_frame`은 `includes`를 합친다. 규칙은 이어 붙이고, 용어는 이름으로 중복을
   제거한다. LLM에는 합쳐진 어휘만 간다(`includes`, `note`는 빼고). 진료 틀당 약 6천 자.
4. 진료 틀 id 목록을 API Literal, 계약 스키마 enum, 웹 타입과 라벨에 반영했다.
   테스트가 이 목록과 프레임 파일이 일치하는지 확인한다.
5. 기본 텍스트 모델을 `DEFAULT_TEXT_MODEL = "gpt-4o"`(app/providers/openai_llm.py)
   한 곳으로 모았다. `OPENAI_TEXT_MODEL`로 바꿀 수 있다. eval 스크립트는
   `OPENAI_MODEL`이 있으면 그것을 먼저 쓴다.
6. 어휘용/평가용 분리:
   - gold에 `"split": "dev" | "eval"` 표시를 붙인다. 기존 ICU/ER은 `eval`이다.
   - `make check-vocab-leakage`: 평가용 녹음의 3단어 이상 문장이 어휘 예시에 들어
     있으면 실패한다. 1~2단어는 표준 용어명이라 허용한다.

## 의도적으로 하지 않은 것

- 실제 말투 예시(spoken_examples)는 일반 표현 1~3개뿐이다. 개발용 녹음에서 보강한다.
- 진료 틀 자동 추천은 없다.
- 진료 틀 2개 이상 동시 선택은 지원하지 않는다(공통 진찰 어휘가 그 역할을 대신함).

## Tests

- `test_clinical_frame.py`: 9개 틀 모두 로드, 공통 진찰 어휘 포함, 용어 중복 없음,
  id와 파일 일치, 공통 용어(복시)가 다른 틀(headache)에서도 유효한지
- `test_provider_caching.py`: 기본 모델이 gpt-4o인지
- `test_vocab_leakage.py`: 문장형 예시만 검사하는지, 띄어쓰기 차이를 무시하는지
- 전체: pytest 284, web typecheck/lint/unit 6, E2E 8 통과

## 남은 위험

- 어휘가 커지면 LLM이 의미가 맞지 않는 용어 후보를 원문 인용과 함께 붙일 수 있다
  (예: "항발작제" 인용에 EEG). 검증기는 인용이 실제로 있는지만 보므로 통과한다.
  모든 후보는 체크리스트에서 의사가 확인한다. eval에서는 context_only 누출로 잡힌다.
- 질환군 진료 틀의 용어는 시작점이다. 신경과 전문의 검토가 필요하다.
- gpt-4o는 mini보다 비용이 높다. 진료당 비용은 출력 JSON 토큰으로 확인한다.

## 녹음 배정 기록

| case | 진료 틀 | split | 비고 |
|---|---|---|---|
| sim_icu_01 | seizure | eval | 2026-10-09 |
| sim_er_01 | stroke | eval | 2026-10-09 |
| sim_mg_01 | neuromuscular | **dev** | 2026-10-10, 신경근육 첫 녹음. 의료진 핵심 구조 미수령이라 gold는 초안이다. |

sim_mg_01(dev)에서 어휘로 옮긴 표현(`learned_from: ["sim_mg_01"]` 표시):

- neuromuscular: respiratory weakness, myasthenic crisis 의심(inference), FVC/spirometry,
  객담 배출 장애
- general_medicine: high-flow nasal cannula, hypercapnia, nasogastric tube, arterial line

dev 녹음의 점수는 어휘를 그 녹음에서 배웠으므로 부풀려져 있다. 개선 효과는 eval 녹음
점수로만 판단한다.

답안 변환기 수정: 줄 전체가 "보호자분 (01:08)"인 헤더를 화자 전환으로 읽는다. 문장
안의 "보호자분 ~"은 기존대로 본문이다(MG 답안에서 보호자 발화가 의사 발화로 읽힌 문제).

# Task 13-a: 검사 결과·소견(findings) 칸 추가

## 배경 (2026-10-10)

tasks/12 실측(gpt-4o, REPEAT=3)에서 체크리스트 부담은 해결됐다(ER 9.3→2.0,
ICU 8.3→3.0). 하지만 ER에서 영상 결과를 보호자에게 설명한 내용은 여전히 3번 모두
놓쳤다.

- 굵은 혈관은 뚫려 있음
- 가는 혈관이 막힘
- perfusion이 버팀
- 시술하면 터질 위험

원인은 스키마에 결과를 담을 칸이 없다는 것이다. `tests`에는 검사 이름·이유·
상태만 있다. task 13은 세 단계로 나눠 하나씩 측정한다: 13-a findings 칸,
13-b 긴 대화 분할 구조화, 13-c 용어 후보 호출 분리. 이번에는 13-a만 한다.

## 구현

- `Finding`: `test_or_exam`, `result`, `interpretation`(의사가 해석을 말했을 때만),
  `source_segment_ids`, `needs_confirmation`. `ClinicalStructure.findings`는 기본값이
  빈 목록이라 이전 저장본도 읽힌다.
- 계약 스키마, mock, 웹 타입, 검토 화면("검사 결과·소견" 칸), 평가 출력에 반영했다.
- 프롬프트 `structure_transcript@0.4.0`:
  - 오더·계획은 `tests`, 나온 결과는 `findings`로 쓴다.
  - 화면이나 사진을 보여주며 설명한 내용(색, 크기, 막힘·뚫림)도 결과다.
  - 결과가 여러 개면 따로 쓴다.
  - 해석은 의사가 말했을 때만, 수치는 원문에 있을 때만 쓴다.
- 프롬프트 예시는 평가 녹음과 겹치지 않는다(`check-vocab-leakage` OK).

## 의도적으로 하지 않은 것

- findings는 체크리스트에 올리지 않는다(체크리스트 부담을 다시 늘리지 않기 위해).
- 13-b(긴 대화 분할), 13-c(용어 후보 호출 분리)는 13-a 측정 뒤에 진행한다.

## Tests

- `test_clinical_frame.py`(+2): findings 없는 예전 저장본 로드, OpenAI strict 스키마 포함
- web unit: 문제 칸을 수정해도 findings 유지
- 전체: pytest 304, web typecheck/lint/unit 6, E2E 8 통과

## 측정 (사용자 장비, tasks/12 결과와 비교)

- ER 소견·근거 항목: finding_main_trunk_open, finding_small_distal_vessel,
  finding_perfusion_holding, plan_procedure_risk_rupture (tasks/12: 0/3, 0/3, 0/3, 0/3)
- 녹음 내용 recall: ER 60%, ICU 81%, MG 60%
- 체크리스트 항목 수가 다시 늘지 않는지, 누출 0 유지, 진료당 토큰

---

# 13-c: 용어 후보 호출 분리

## 왜

13-a 측정에서 ER은 frame-term recall 8%, inference 후보 0개였다. 구조화 한 번의 호출에
진료 틀 어휘 전체(입력)와 모든 칸(출력)이 같이 들어가서, 긴 대화에서는 용어 후보 칸이
가장 먼저 줄어들었다. 용어 후보 찾기를 별도 호출로 나눈다.

## 구현

- `structure_encounter`는 두 번 호출한다.
  1. `structure_transcript@0.5.0`: 진료 틀을 받지 않는다. `term_candidates`는 항상 빈 목록으로 두고,
     모델이 채워도 버린다.
  2. `term_candidates@0.1.0`: 진료 틀이 있을 때만 호출한다. 대화와 틀 어휘만 받아서
     `{"term_candidates": [...]}`(`TermCandidateList`)만 반환한다. 결과는 이전과 같은
     `validate_term_candidates`(틀 일치, 목록에 있는 용어, 원문 그대로 인용, 위험도 덮어쓰기)를 거친다.
- 진료 틀이 없으면 두 번째 호출을 하지 않는다. 비용과 지연은 그대로다.
- `PROMPT_VERSION` = `structure_transcript@0.5.0+term_candidates@0.1.0` (버전 기록에 둘 다 남는다).
- mock과 OpenAI provider에 `term_candidates` 호출을 추가했다(strict 스키마).
- 평가 스크립트는 바꾸지 않았다. StageTimer가 두 호출의 토큰을 합산하고, structure 지연에
  두 호출이 모두 들어간다.

## 의도적으로 하지 않은 것

- 두 호출의 병렬 실행: 먼저 품질을 측정한다. 지연이 문제가 되면 그때 한다.
- 13-b(긴 대화 분할): 13-c 측정 뒤에도 ER 압축이 남으면 진행한다.

## Tests

- `test_clinical_frame.py`:
  - 틀 어휘는 용어 후보 호출에만 간다
  - 틀이 없으면 용어 호출이 없고, 구조화 호출의 후보도 버린다
  - 구조화 호출의 후보는 용어 호출 결과로 바뀐다
- 전체: pytest 306, web typecheck/lint/unit 6, E2E 8 통과, `check-vocab-leakage` OK

## 측정 (13-a 결과와 비교)

- frame-term recall: ER 8%, ICU 67%, MG 60%. ER inference 후보는 0개였다.
- 녹음 내용 recall: ER 62%, ICU 78%, MG 60% (떨어지면 안 된다)
- 체크리스트 항목 수, 누출 0, 진료당 토큰(용어 호출만큼 입력이 늘어난다)

## 13-c 측정 결과와 후속 수정

측정 (gpt-4o, REPEAT=3):

| | ER | ICU | MG |
|---|---|---|---|
| frame-term recall | 8% → 33% | 67% → 67% | 60% → 23% |
| inference 후보 | 0 → 2.3 | 1.3 | 1.3 |
| 용어 후보 수 | 8.0 (7-9) | 4.7 (4-6) | 5.0 (1-10) |
| 누출 | 0 | 0 | 0 |

이 결과를 보고 두 가지를 고쳤다.

1. 채점: `term_candidates[].spoken_text`는 대화 원문을 그대로 옮긴 문구라서 녹음 내용 항목의
   키워드가 들어 있다. 그런데도 채점기는 이걸 "요약이 담았다"로 세고 있었다. 이제 녹음 내용
   항목이 용어 후보 인용에서만 맞으면 miss로 센다. 누출과 frame_term 항목은 계속 모든 칸을 본다.
   평가 출력에 "found only in term-candidate quotes" 개수를 따로 보여 준다.
2. OpenAI 호출에 `temperature=0`을 쓴다. 기본값 1.0에서는 같은 MG 대화로 실행할 때마다 용어
   후보가 1개, 4개, 10개로 달랐다. 모든 호출이 원문을 뽑아내거나 다시 쓰는 일이라 다양성이
   필요 없다.

이 수정 뒤의 녹음 내용 recall은 13-a 숫자와 직접 비교하지 않는다. 13-a 때도 일부 항목은
용어 후보 인용으로 맞았다. 새 기준선은 다시 측정해서 잡는다.

### temperature 0 반복 루프 대응

재측정에서 ER 구조화 호출이 temperature 0에서 같은 내용을 반복하다가 출력 한도(16,384 토큰)에
걸려 JSON 없이 실패했다(`LengthFinishReasonError`). ICU와 MG는 정상이었고, MG 용어 후보는
8-9개로 안정됐다(frame-term recall 23% → 67%).

- 출력 상한을 `MAX_OUTPUT_TOKENS=8000`으로 둔다. 정상 출력은 2-3k라서, 루프에 빠지면 더 빨리,
  더 싸게 끊긴다.
- 상한에 걸리면 API 기본 temperature(1.0)로 한 번만 다시 호출한다. 이전 평가에서 기본값은
  루프에 빠진 적이 없다. 두 번째도 걸리면 `LLM_PROVIDER_FAILED`로 실패한다(내용은 남기지 않는다).
- 재시도는 stage의 `retry_count`에 남고, 두 번의 토큰을 모두 센다. 평가 출력에 재시도 횟수를 보여 준다.

### ER 재측정: temperature를 호출별로

출력 상한과 재시도를 넣고 다시 쟀더니 ER은 3번 모두 재시도했다(`retried 3`). structure 지연은
47.2s, 출력은 10.7k 토큰이었다. 구조화 호출은 긴 대화에서 temperature 0이면 매번 루프에 빠진다.
반면 temperature 0으로 효과를 본 것은 용어 후보 호출이었다(MG 후보 수 1-10 → 8-9, ER frame-term
recall 92%).

- `TEMPERATURE_BY_PROMPT = {"term_candidates": 0.0}`. 나머지 호출은 기본값 1.0으로 되돌린다.
- 출력 상한과 한 번의 재시도는 안전장치로 남긴다.

# 13-d: plan·치료·병동 칸 보강 (MG)

새 채점 기준으로 MG 녹음 내용 recall은 53%였다. 5.3개 항목은 용어 후보 인용에만 있었다.
놓친 항목은 대부분 호흡 보조와 계획이었다: 산소가 부족함, 더 강한 산소 방법, 마스크, 동맥관,
약을 위한 콧줄, 이산화탄소, 항생제, 일반 병실은 아직 이름, 보호자에게 다시 묻기, 상의할 시간,
중환자실 관찰. 프롬프트에 `plan` 규칙이 없었다.

`structure_transcript@0.6.0`:

- `treatments_given`: 지금 쓰는 산소·호흡 보조, 꽂아 둔 관과 그 목적, 투여 중인 약(의사가 말한 이름 그대로).
- `plan`(새 규칙):
  - 계획은 하나씩 따로 쓴다.
  - 지금 치료가 부족하다는 설명과 다음 단계 방법, 고려하는 대안 각각.
  - 새로 넣을 관이나 줄과 그 목적.
  - 보호자에게 다시 묻기, 가족이 상의할 시간도 계획이다.
- `disposition`: 옮기는 곳과 이유, 아직 옮길 수 없는 곳과 이유.
- `problems`: 의사가 일상어로 설명한 몸 상태.
- 예시는 일반 문구로 썼다(`check-vocab-leakage` OK). MG는 개발용 녹음이라 MG 점수는 참고로만
  보고, 효과는 평가용 녹음(ER, ICU)이 떨어지지 않는지로 판단한다.

### 13-d 측정: plan 보강 효과 없음 → 진단 도구

`structure_transcript@0.6.0` 결과: ER 67%, ICU 80%, MG 50%. MG에서 용어 후보 인용에서만 맞은
항목은 6.0개였다. 재시도는 0이었고 ER 지연은 16.1s로 정상이었다. MG에서 고유량 산소, 마스크,
동맥관, 보호자에게 다시 묻기, 상의할 시간, 항생제는 여전히 놓쳤다.

- `make diagnose-structure`: 저장된 평가 출력으로 놓친 녹음 내용 항목을 분류한다. API를 다시
  부르지 않는다.
  - partial: 한 항목에 키워드 묶음 일부만 있음. 바꿔 말했거나 일부를 뺐다.
  - split: 모든 묶음이 있지만 여러 항목에 흩어져 있음.
  - omitted: 요약 어디에도 없음.
  - quote: 용어 후보 인용에 통째로 있는지 표시한다.
  - 정답지 키워드(이미 repo에 있음)와 칸 이름만 출력한다. 출력이나 전사 본문은 출력하지 않는다.
- `term_candidates@0.2.0`: 한 구절이 여러 용어에 해당하면 용어마다 후보를 쓴다. MG myasthenic
  crisis는 "숨쉬는 힘" 구절이 이미 호흡근 약화로 쓰여 3번 모두 빠졌다.

# 13-e: 보완 호출 (coverage_check)

## 왜

`make diagnose-structure` 결과, 놓친 녹음 내용 항목의 62%(MG 24/39)와 68%(ER 23/34)가 요약
어디에도 키워드가 없었다(omitted). 바꿔 말한 것(partial)이 아니었다. 같은 항목을 3번 모두
빠뜨렸고, 그 칸의 규칙(findings 13-a, plan 0.6.0)이 있어도 빠졌다. 구조화 호출은 칸마다 1-3개만
쓰고 나머지를 버린다. 13-c에서 확인했듯이 한 가지 일만 맡은 호출은 더 빠짐없이 찾는다.

## 구현

- `structure_encounter`: ① `structure_transcript` → ② `coverage_check` → ③ `term_candidates`(진료 틀이 있을 때).
- `add_missed_facts`:
  - 대화와 ①의 결과(term_candidates 제외)를 보낸다.
  - 같은 `ClinicalStructure` 형식으로 **빠진 항목만** 받아 칸마다 뒤에 덧붙인다.
  - 대소문자와 공백만 다른 완전 중복은 버린다. 바꿔 말한 중복은 프롬프트가 막는다.
  - ②가 돌려준 term_candidates는 버린다.
- `prompts/coverage_check.md` 0.1.0:
  - 발화를 하나씩 확인하는 체크 목록이 있다(결과, 결정과 이유, 위험, 치료·장치, 계획과 다음 단계,
    병동 이동, 보호자 절차, 환자·보호자 진술).
  - 의사가 쓴 단어 그대로 쓴다. 원문에 없는 사실은 쓰지 않는다.
  - 빠진 것이 없으면 빈 칸으로 반환한다.
- temperature는 기본값(1.0)이다. 구조화 호출과 같은 종류라 0이면 반복 루프 위험이 있다.
- 덧붙인 결정도 기존 체크리스트 규칙을 그대로 탄다(하지 않음, 조건부 → 의사 확인).
- `PROMPT_VERSION` = structure + coverage + term_candidates.
- 평가 출력에 호출별 시간과 토큰(`per call`)을 보여 준다.

## 의도적으로 하지 않은 것

- ②가 덧붙인 항목에 표시를 달거나 따로 검수하게 하지 않았다. 효과와 누출을 먼저 측정한다.
- 바꿔 말한 중복을 의미로 걸러 내지 않았다.

## Tests

- `test_coverage_check.py`(+4):
  - 빠진 항목이 뒤에 덧붙는다
  - 완전 중복과 term_candidates는 버린다
  - 빠진 것이 없으면 그대로
  - PROMPT_VERSION에 coverage가 기록된다
- `test_clinical_frame.py`: 호출 순서에 coverage_check가 들어갔다.
- 전체: pytest 317, E2E 8, `check-vocab-leakage` OK

## 측정 기준 (13-d 0.6.0)

| | ER | ICU | MG |
|---|---|---|---|
| 녹음 내용 recall | 67% | 80% | 50% |
| frame-term recall | 67% | 100% | 80% |
| 누출 | 0 | 0 | 0 |
| 지연 | 16.1s | 17.1s | 15.0s |

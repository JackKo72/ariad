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

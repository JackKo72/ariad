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

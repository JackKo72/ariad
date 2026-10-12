# Task 15: LLM 호출 병렬화

## 왜

tasks/14 측정에서 진료 직후 요약까지 ER 26.9s, ICU 24.0s가 걸렸다. LLM 호출 다섯 개가
순서대로 돌았기 때문이다. 다른 호출의 결과가 필요한 것은 보완 호출(구조화 결과를 받음) 하나뿐이다.

## 구현

```
전:  enrichment → structure → coverage → term_candidates → frame_checklist
후:  enrichment ─────────────────────────────┐
     structure → coverage ───────────────────┤→ 환자 설명 → 저장
     term_candidates (진료 틀) ──────────────┤
     frame_checklist (목록 있는 진료 틀) ────┘
```

- `structure_encounter`: `ThreadPoolExecutor(max_workers=3)`로 [구조화 → 보완], 용어 후보,
  필수 확인을 동시에 돌린다. 어느 갈래든 실패하면 지금처럼 예외가 올라가 처리 실패가 된다.
- `POST /process`: enrichment를 스레드 하나에서 구조화 단계와 동시에 돌린다.
- `StageTimer`: 여러 스레드가 기록하므로 append를 lock으로 감쌌다.
- 평가 스크립트도 같은 방식으로 돌리고 wall-clock 지연을 보여 준다.
- worker나 큐는 쓰지 않는다. 한 요청 안의 스레드일 뿐이다(CLAUDE.md).

## 의도적으로 하지 않은 것

- 환자 설명 호출은 구조화 결과가 필요해서 마지막에 그대로 둔다.
- async 클라이언트로 바꾸지 않았다. 동기 SDK와 스레드만으로 충분하다.

## Tests

- `test_coverage_check.py`(+2):
  - 구조화, 용어 후보, 필수 확인 세 호출이 동시에 시작하는지 확인한다(Barrier, 순서대로 돌면 실패).
  - 한 갈래가 실패하면 단계 전체가 실패한다.
- `test_clinical_frame.py`: 호출 순서 대신 "보완은 구조화 다음"만 확인한다.
- 전체: pytest 333(3번 반복 실행), E2E 8

## 함께 반영

- gold `frame_checks`(의료진 확인, 2026-10-12):
  - ER: onset_time, hemorrhage → not_mentioned
  - ICU: asm_plan, eeg → not_mentioned

## 측정 기준 (tasks/14)

| | ER | ICU |
|---|---|---|
| 지연(순차) | 26.9s | 24.0s |
| 가장 긴 갈래 | enrichment 8.7s / structure+coverage 10.9s | enrichment 10.1s / structure+coverage 7.8s |

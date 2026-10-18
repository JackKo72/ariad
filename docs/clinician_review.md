# ARIAD 2단계 의료진 검토표

작성: 2026-10-10 · 대상 브랜치 `claude/sharp-goldberg-leijbj`

2단계 코드는 동작하지만, 아래 값과 문구는 **의료진이 정해야 하는 것**이라 비워 두었거나 초안으로 표시했다. "참고 제안"은 설계 문서(`docs/ARIAD_stage2_design.md`)에서 찾을 수 있는 근거를 정리한 것일 뿐 적용하지 않았다. 결정하면 해당 파일의 값을 바꾸고 `review_status`를 `clinician_reviewed`로 올린다.

확인 명령: `python3 tests/test_catalog.py` (남은 TODO 목록), `python3 -m pytest -q`

## 1. 카탈로그 수치 (`catalog/actions.yaml`, `TODO_CLINICIAN` 15개)

`tests/test_catalog.py`가 이 표에 모든 TODO 경로가 있는지 검사한다.

| 코드 | 경로 | 무엇 | 설계 문서 근거 | 참고 제안 (미적용) | 결정 |
| --- | --- | --- | --- | --- | --- |
| D1 | `D1.default_target.value` | 지중해식 7문항 점수 목표 | Part 2-2 "주 1회 7문항 (축약판)" — 문항·점수 기준 없음 | 문항 구성(§3 Q-D1-01)부터 정해야 함 | |
| D2 | `D2.default_target.value` | 국물 남긴 날 목표 (주 N일) | Part 5-3 예시 JSON `6 days_per_week` (근거 표 아님) | 6 | |
| D3 | `D3.atomic_behaviors` | 칼륨 원자 행동 | Part 2-2에 D3 행 없음. Part 1-1: 3,500–5,000 mg/일, 음식으로 | 행동 정의 필요 | |
| D3 | `D3.metric_type` | 판정 방식 | — | | |
| D3 | `D3.default_target.value` | 목표값 | — | | |
| D3 | `D3.default_target.unit` | 단위 | — | | |
| D3 | `D3.default_target.comparator` | 이상/이하 | — | | |
| D3 | `D3.check_method.channel` | 체크 채널 | — | | |
| D3 | `D3.check_method.description` | 체크 설명 | — | | |
| D3 | `D3.check_method.cadence` | 체크 주기 | — | | |
| D4 | `D4.default_target.value` | 튀김·삼겹살 주 N회 이하 | Part 2-2 "주 N회 이하" (N 미정) | | |
| P1 | `P1.default_target.value` | 주간 걷기 분 | Part 1-1: 중강도 150–300분/주, 뇌졸중은 가능하면 40분×3–4회, 불가 시 맞춤 | 150 (하한) — 단 뇌졸중 환자는 진료 합의값 우선 | |
| W1 | `W1.outcome_target.value` | 감량 목표 % | Part 1-1: 5–10% (KDA ≥5, ADA 5–7) | 5 | |
| H1 | `H1.default_target.routine.value` | 평소 가정혈압 측정일 | Part 2-2 "평소 주 2–3일" | 3 | |
| H2 | `H2.default_target.value` | 자가혈당 측정 횟수 | Part 1-1 "빈도 개별화", Part 2-2 "처방대로" | 기본값 없이 처방마다 입력 | |

## 2. 판정 규칙 (`config/judge.yaml`, `app/stage2/judge.py`)

| 항목 | 현재 | 근거 | 결정 |
| --- | --- | --- | --- |
| 완전/부분/응답률 기준 | 0.8 / 0.5 / 0.5 | Part 3-2 표 그대로 | 확인 |
| "주 N잔 이하" 초과 시 이행률 | 목표/실제 (예: 2잔 목표에 4잔 → 0.5 부분 이행) | 설계에 없음 (구현 판단) | 0으로 볼지 |
| 금연 이행률 | 안 피운 날 / 응답한 날 (개비 수 무관) | 설계에 없음 (구현 판단) | |
| M1 목표 vs 질문 주기 | 목표 주 7일, 질문 주 3회 → 매번 "했다"여도 3/7=0.43 미이행 | Part 2-2 "하루 1회 / 주 3회 Y/N" 불일치 | 목표를 주 3일로 낮출지, 질문을 매일로 바꿀지 |
| 답변 → `CheckIn.value` | 미구현. D2 "반"을 남김(1)으로 볼지 0으로 볼지 등 | 설계에 없음 | |
| 측정형(H1·H2) 판정 | 측정 안 한 날 = 미이행. 0건일 때만 판정 불가 | Step 7에서 발견해 수정 | 확인 |

## 3. 환자에게 나가는 문구 (`catalog/questions.yaml`, 전부 `draft_unreviewed`)

| question_id | 환자용 문구 | 출처 | 결정 |
| --- | --- | --- | --- |
| Q-D1-01 | `TODO_CLINICIAN` (7문항 미정 → 발송 안 됨) | — | |
| Q-D2-01 | 오늘 국물은 얼마나 드셨나요? (안 먹음/반/다) · 보호자: 오늘 국 간을 줄이셨나요? | Part 2-2, 2-3 C | |
| Q-D3-01 | `TODO_CLINICIAN` (발송 안 됨) | — | |
| Q-D45-01 | 튀김·삼겹살 몇 번 / 단 음료 몇 번 / 생과일 여부 (3문항) | Part 2-2 행동 목록 기반 초안 | |
| Q-P1-01 | 오늘 걸으셨나요? 몇 분? | Part 2-2 | |
| Q-P2-01 | 오늘 의자 일어서기·밴드 운동을 하셨나요? 몇 세트 하셨나요? | 초안 | |
| Q-P3-01 | 일어나서 3분 움직이셨나요? | 초안 | |
| Q-W1-01 | 오늘 아침 공복, 소변 본 뒤 잰 체중을 입력해 주세요. | Part 2-2 기반 | |
| Q-A1-01 | 지난 7일 중 술 마신 날은 며칠인가요? / 모두 몇 잔 드셨나요? | Part 2-2 | |
| Q-S1-01 | 오늘 담배(전자담배 포함) 피우셨나요? | Part 2-2 | |
| Q-S1-02 | 이번 주에 금연약을 드시고 금연 상담을 받으셨나요? | 초안 | |
| Q-M1-01 | 오늘 5분 호흡운동을 하셨나요? | 초안 | |
| Q-H1-01 | 오늘 잰 혈압을 입력해 주세요. | 초안 | |
| Q-H2-01 | 오늘 잰 혈당을 입력해 주세요. | 초안 | |

보호자용 문구는 같은 파일의 `caregiver` 필드에 있다.

## 4. Red flag (`config/red_flags.yaml`, `draft_unreviewed`)

- 범주 5개: 새 신경학적 증상, 흉통, 실신, 혈당 <70 mg/dL, 반복 낙상 (Part 3-3 그대로).
- 검토할 판단:
  - "마비" 단독은 잡지 않는다 ("편마비로 걷기 힘듦"은 C-PHY 예시). 발생·변화 표현과 함께일 때만.
  - 단일 낙상은 red flag 아님 (설계: "반복 낙상").
  - 어지러움은 red flag 아님 (설계 표상 MED).
  - 부정문("가슴은 안 아파요")도 걸린다 — 과탐 쪽으로 기울임.
- 안내 문구: "지금 증상이 있으면 즉시 119에 전화하거나 가까운 응급실로 가세요. 담당 의료진에게도 알림을 보냈습니다." 처치 지시(당분 섭취 등)는 설계에 없어 넣지 않았다.

## 5. 리포트 제안 문구 (`config/report.yaml`, `draft_unreviewed`)

| 4주 판정 | 제안 |
| --- | --- |
| 완전 이행 | 현재 목표 유지 |
| 부분 이행 | 목표 유지, 주요 사유 대응 |
| 미이행 | 목표 하향 또는 대체 행동 검토 |
| 판정 불가 | 응답 장벽(측정 문제)부터 확인 |

사유별 기본 대응(`config/barrier.yaml`)은 Part 3-3 표 그대로다.

## 6. 평가셋 정답 라벨 (전부 `draft_unreviewed`)

| 파일 | 건수 | 판단이 갈릴 수 있는 것 |
| --- | --- | --- |
| `tests/fixtures/visits/*.json` | 진료 20건, 지시 34개 | V07 "체중 5% 줄이는 게 목표"를 지시로 봄 · V14 첫 반응이 "혈압계 고장"이라 `unclear` · V17 저혈당 대처는 지시 아님 · V19 "운동은 아직 하지 마시고"는 이행 대상 아님 |
| `tests/fixtures/barriers/responses.json` | 사유 50건 | B18 "같이 사는 아들이 담배를 피워서 저도 참기가 어려워요" O-SOC (M-AUT 가능) · B34 "또 쓰러질까 봐 불안" M-EMO |
| `tests/fixtures/barriers/red_flags.json` | red flag 10건 + 음성 6건 | 빠진 대표 표현이 있는지 |

## 7. 설계 충돌에 대한 결정 (적용함, 확인 필요)

| 충돌 | 결정 | 위치 |
| --- | --- | --- |
| 시나리오 A: 하루 2문항인데 매일 항목(S1·D2) 2개 + 걷기 → 걷기가 한 번도 안 물어짐 | 의료진이 항목별 체크 주기를 바꿀 수 있게 함(`ActionItem.check_cadence`). A는 상한 3, 걷기는 주 3회(월·수·금) → 걷기 날만 3문항. 승인 시 `never_asked_items`가 이런 플랜을 막는다 | `sim/scenarios.yaml`, `app/stage2/checkin.py` |
| 시나리오 B: 근무 중 알림 2회인데 판정은 카탈로그 3회 기준 | 같은 `check_cadence`로 2회/일 설정, 목표도 하루 2회 | `sim/scenarios.yaml`, `app/stage2/judge.py` |

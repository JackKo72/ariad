# Task 10: 진료 틀(clinical frame) 입력 + 구조화 칸 확장 + 의사 검수 체크리스트

## 배경 (2026-10-10)

tasks/09 실측(정답 전사 입력, ICU 5분 / ER 13분 역할극):

| | gpt-4o-mini | gpt-4o |
|---|---|---|
| ER 녹음 내용 recall | 30% | 50% |
| ICU 녹음 내용 recall | 56% | 33% |
| 녹음에 없는 용어 생성 | 0 | 1 (EVT) |

모델을 바꿔도 결과가 일관되게 오르지 않았다. 반복해서 놓친 항목은 기존 스키마
(`problems / tests / medications / plan`)에 담을 칸이 없는 종류였다. 결정(특히
"하지 않음"), 시행한 치료, 동의서, 입원 병동, 예후와 연명의료, 보호자 진술이다.

사용자 결정:

- 용어 변환은 의료진이 큰 틀(stroke/seizure)을 골랐을 때만 허용한다.
- 부정·결정 같은 항목은 의사가 검수한다.

## Outcome

의료진은 처리 시작 전에 진료 틀을 고를 수 있다. 결과 화면에서는 결정, 치료,
동의, 병동, 예후, 보호자 발화를 따로 보고, "하지 않음/조건부" 결정과 용어 후보를
체크리스트로 확인한 뒤에만 승인할 수 있다.

## 구현

1. `ClinicalStructure`에 칸 추가(모두 기본값 빈 목록이라 기존 저장본도 읽힘):
   - `treatments_given`, `consents`, `disposition`, `prognosis_and_goals`
   - `decisions`: `status` = `decided_to_do` / `decided_not_to_do` / `conditional` / `undecided`.
     조건부 결정의 조건은 `condition`, 의사가 말한 이유는 `rationale`.
   - `family_statements`: `report` / `question` / `request`
   - `term_candidates`: `spoken_text` → `term` (진료 틀 용어만)
   - 계약 스키마 `packages/contracts/schema/clinical_structure.schema.json`, 웹 타입,
     mock을 함께 갱신했다. OpenAI strict 모드 스키마 변환도 확인했다.
2. 진료 틀 `prompts/frames/{stroke,seizure}.json`: 허용 용어, 그 용어를 가리키는
   말의 예시, 틀 규칙.
   - 예시 문장은 평가 답안에서 옮기지 않고 따로 썼다(평가 점수 부풀림 방지).
     "뇌졸중 집중치료실", "내시경 초음파" 두 개는 표준 용어명이라 답안과 겹친다.
3. `app/pipeline/frames.py`의 `validate_term_candidates`: 아래 후보는 기계적으로 제거한다.
   - 틀을 고르지 않았거나 다른 틀을 가리키는 후보
   - 목록에 없는 용어
   - 원문에 없는 인용(띄어쓰기 차이는 허용)
4. `structure_encounter(..., clinical_frame=)`는 틀 파일을 LLM 입력에 넣고 응답을 검증한다.
   프롬프트는 `structure_transcript@0.2.0`.
5. 환자 설명 단계에는 `term_candidates`를 비운 구조화 결과만 넘긴다. 검수 전
   추정 용어가 환자 문장에 섞이지 않게 하기 위해서다.
6. `app/pipeline/review_checklist.py`: 체크리스트 대상은 다음과 같다.
   - 시행이 아닌 결정, 그리고 needs_confirmation 표시된 결정
   - 모든 용어 후보
   - needs_confirmation 표시된 약물

   항목 id는 내용 hash라서, 내용을 수정하면 이전 확인은 무효가 된다.
7. API:
   - `POST /process` 선택적 body `clinical_frame`. 고른 틀은 version에 기록한다
     (DB 컬럼 `encounter_versions.clinical_frame`, 자동 migration).
   - `GET /encounters/{id}` 응답에 `review_checklist`.
   - `POST /approve`는 `acknowledged_review_item_ids`가 모자라면
     `REVIEW_CHECKLIST_INCOMPLETE`(409)로 거부한다.
8. 웹:
   - 처리 시작 화면과 재처리 화면에 진료 틀 선택 칸
   - 검토 화면에 새 칸 표시와 체크리스트
   - 모든 항목을 체크하기 전에는 승인 버튼 비활성
9. 평가: `FRAMES=`가 채점뿐 아니라 실제 구조화 단계에도 전달된다. 출력에는 새 칸이
   몇 개 채워졌는지와 체크리스트 항목 수가 함께 나온다. 출력 JSON은 transcript 옆
   (`data/`)에 저장하며, 저장소의 gold 폴더에는 쓰지 않는다.

## 의도적으로 하지 않은 것

- enrichment 단계는 바꾸지 않았다(진료 틀은 구조화 단계에만 들어간다).
- 새 칸의 편집 UI. 지금은 표시와 체크만 된다. 수정은 기존처럼 problems 칸과
  draft API로 한다.
- EMR 맥락 입력. midazolam, EEG, SCMP, CIN처럼 틀만으로는 알 수 없는 사실은
  여전히 만들지 않는다.
- 진료 틀 자동 추천. 틀 선택은 항상 의료진이 한다.

## Tests

- Unit `test_clinical_frame.py`(16):
  - 틀 파일 로드
  - 후보 검증(유지 1개, 제거 5가지 경우, 띄어쓰기 허용)
  - 틀이 있을 때만 LLM 입력에 들어가는지
  - 환자 설명에 용어 후보가 빠지는지
  - 체크리스트 대상 선정과, 내용 수정 시 확인 무효화
- Integration `test_clinical_frame_review.py`(4):
  - body 없는 기존 호출 호환
  - 틀 기록
  - 모르는 틀 거부(422)
  - 확인 없으면 승인 거부, 확인하면 승인되고 틀이 승인본에 남음
- Web unit: 기존 fixture 갱신, 문제 칸을 수정해도 새 칸이 유지되는지
- E2E `clinical_frame_review.spec.ts`: 틀 선택 → 처리 → 결정 추가 → 체크 전 승인
  비활성 → 체크 후 승인

## 다음 측정 (사용자 장비)

```bash
make eval-structure TRANSCRIPT=$D/sim_er_01.transcript.json  GOLD=tests/evals/gold/sim_er_01.gold.json  REAL=1 FRAMES=stroke
make eval-structure TRANSCRIPT=$D/sim_icu_01.transcript.json GOLD=tests/evals/gold/sim_icu_01.gold.json REAL=1 FRAMES=seizure
```

비교할 지표는 tasks/09 기준선 대비 다음과 같다.

- 녹음 내용 recall
- frame-term recall
- 누출 0 유지
- 체크리스트 항목 수

## 남은 위험

- 결정의 극성(하지 않음 ↔ 시행)은 여전히 LLM이 정한다. 체크리스트가 사람
  확인을 강제하지만, LLM이 "하지 않음" 결정을 아예 `decided_to_do`로 적으면
  체크리스트에 오르지 않는다(needs_confirmation을 붙이지 않은 경우).
- 용어 후보 검증은 "허용 목록 안의 용어인가"와 "원문 인용이 맞는가"만 본다.
  인용과 용어의 의미 연결이 맞는지는 의사가 판단해야 한다.
- 진료 틀 어휘는 두 개, 각 6~11개 용어로 시작점일 뿐이다.

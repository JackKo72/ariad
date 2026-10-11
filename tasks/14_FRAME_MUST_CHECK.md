# Task 14: 질환별 필수 확인 항목 (frame must-check)

## 목표

의료진이 고른 진료 틀에 "이 질환이면 꼭 봐야 할 항목" 목록이 있으면, 이번 진료에서 각 항목을
다뤘는지(언급됨/언급 안 됨) 표시한다. 보완 호출(13-e)은 "말했는데 빠진 것"을 찾고, 이 단계는
"질환 기준으로 다뤘는지"를 본다.

- "언급 안 됨"은 의료진을 위한 정보다. 승인을 막지 않고, 모델이 내용을 채우지도 않는다(사용자 결정).
- 대상: stroke, seizure, parkinson disease(`movement`), dementia(`cognitive`), radiculopathy(`spine`).

## 구현

- `prompts/frame_checks/<frame>.json`: 항목 목록(`id`, `label`, `look_for`). **초안(status: draft)이며
  의료진 검토가 필요하다.** 일반 임상 기준으로 썼고, 녹음에서 옮기지 않았다.
- `prompts/frame_checklist.md` 0.1.0: 대화와 목록을 받아 항목마다 `mentioned`(근거 원문 구절) 또는
  `not_mentioned`를 돌려준다. temperature 0.
- `app/pipeline/frame_checks.py`:
  - 결과는 항상 목록 전체이고, 순서와 label은 파일 그대로 쓴다. 모르는 id는 버리고, 빠진 id는
    `not_mentioned`로 채운다.
  - `mentioned`인데 근거 구절이 대화에 글자 그대로 없으면 `not_mentioned`로 내린다.
- 호출 순서: 구조화 → 보완 → 용어 후보 → 필수 확인. 마지막 둘은 진료 틀이 있을 때만 돌고,
  필수 확인은 목록이 있는 진료 틀일 때만 돈다.
- `ClinicalStructure.frame_checks`: 기존 저장본은 빈 목록으로 읽힌다. 다음에는 들어가지 않는다:
  - 환자 설명 입력
  - 보완 호출 입력
  - 구조화 프롬프트(빈 목록으로 둔다)
- 웹 검토 화면: "진료 틀 필수 항목 (n/N 언급됨, 정보용·승인과 무관)". ✓ 항목은 근거 구절과 함께,
  – 항목은 "언급 안 됨"으로 보여 준다.
- 평가: 항목별 언급 횟수를 출력한다. gold에 `frame_checks`가 있으면 일치율도 낸다(`tests/evals/gold/README.md`).
- `check-vocab-leakage`가 목록의 label과 look_for도 평가 녹음과 대조한다.

## 의도적으로 하지 않은 것

- "언급 안 됨" 확인을 승인 조건으로 만들지 않았다.
- 다른 진료 틀(headache, dizziness, neuromuscular, icu, general_neuro)의 목록은 만들지 않았다.
- ER(stroke), ICU(seizure) 평가 녹음의 항목별 정답은 의료진이 적어야 해서 비워 두었다.

## Tests

- `test_frame_checks.py`(+11):
  - 목록 전체·순서·label 강제
  - 근거 없는 mentioned 내림, not_mentioned 구절 비움
  - 다섯 목록이 있고 id가 중복되지 않음
  - 목록 파일과 진료 틀이 일치함
  - 목록 없는 진료 틀은 호출하지 않음
  - 구조화 결과에는 들어가고 환자 설명과 보완 호출에는 들어가지 않음
  - 버전 기록
- `test_vocab_leakage.py`(+1), OpenAI strict 스키마 호환(+2), web unit(frame_checks 유지), E2E(stroke 15개 모두 "언급 안 됨", 승인 가능)

## 초안 목록 (검토용)


### stroke (뇌졸중) (15개)

| id | 항목 | 해당하는 것 |
|---|---|---|
| `onset_time` | 증상 시작 시각 / 마지막 정상 시각 | 언제 증상이 시작됐는지, 또는 마지막으로 괜찮았던 때 |
| `deficit` | 주 증상과 신경학적 결손 | 편측 마비, 말·언어 장애, 시야, 감각, 어지럼 등 어떤 증상이 어느 쪽에 있는지와 정도(NIHSS 포함) |
| `hemorrhage` | 뇌출혈 여부 | 뇌 영상에서 출혈이 있는지 없는지 |
| `vessel_occlusion` | 혈관 폐색 여부와 부위 | 혈관 영상에서 막힌 혈관이 있는지, 어느 혈관인지 |
| `core_perfusion` | 경색 범위·관류 상태 | 이미 손상된 범위, 혈류가 떨어진 범위, 살릴 수 있는 범위에 대한 설명 |
| `thrombolysis` | 정맥 혈전용해제 결정 | 혈전용해제를 쓰는지, 쓰지 않는다면 이유(시간, 금기 등) |
| `thrombectomy` | 혈관내 혈전제거술 결정 | 시술을 하는지, 하지 않는지, 조건부인지와 이유 |
| `prior_antithrombotic` | 기존 항혈전제 복용 | 원래 먹던 항혈소판제·항응고제가 있는지 |
| `antithrombotic_plan` | 항혈소판제·항응고제 계획 | 앞으로 쓸 항혈전제, 보류, 변경과 이유 |
| `blood_pressure` | 혈압 목표·조절 | 혈압을 어느 정도로 유지하는지, 혈압약 조절 |
| `swallow` | 삼킴 평가·금식 | 삼킴 검사 전 금식, 식사 시작 시점 |
| `etiology_workup` | 원인 검사 계획 | 심전도 감시, 심장 초음파, 혈관 검사 등 원인을 찾는 검사 |
| `worsening` | 악화 가능성과 대응 | 증상이 나빠질 수 있다는 설명과 나빠지면 어떻게 하는지 |
| `disposition` | 입원 병동 | 뇌졸중 집중치료실, 중환자실, 일반 병동 중 어디로 가는지 |
| `procedure_consent` | 시술·조영제 위험 설명과 동의 | 시술이나 조영제의 위험 설명, 동의서 |

### seizure (경련/발작) (15개)

| id | 항목 | 해당하는 것 |
|---|---|---|
| `semiology` | 발작 양상 | 어떤 모습이었는지(전신·한쪽, 의식 소실, 눈 돌아감, 굳음·떨림) |
| `duration_count` | 지속 시간·횟수 | 얼마나 오래, 몇 번 했는지, 사이에 깨어났는지 |
| `recovery` | 발작 후 회복 | 의식이 돌아왔는지, 발작 후 마비·혼동이 있는지 |
| `history` | 첫 발작 여부·과거력 | 처음인지, 기존 뇌전증이나 이전 발작이 있는지 |
| `provoking` | 유발 요인 | 수면 부족, 음주, 약 중단, 발열, 혈당·전해질 이상 등 |
| `adherence` | 기존 항경련제 복용 | 먹던 항경련제와 빠뜨림 여부 |
| `acute_treatment` | 급성기 치료와 반응 | 발작을 멈추려고 쓴 약과 효과 |
| `airway` | 기도·호흡 관리 | 산소, 삽관, 인공호흡기 여부 |
| `labs` | 혈액검사 | 혈당, 전해질, 약물 농도, 감염 수치 |
| `imaging` | 뇌 영상 | CT·MRI 계획 또는 결과 |
| `eeg` | 뇌파 | 뇌파 검사 계획 또는 결과 |
| `asm_plan` | 항경련제 계획 | 약 시작, 추가, 용량 변경 |
| `cause` | 원인 감별 | 발작 원인에 대한 설명이나 감별 |
| `safety` | 안전 교육 | 운전, 수영, 높은 곳, 혼자 목욕 등 주의 |
| `rescue` | 재발 시 대처 | 다시 발작하면 어떻게 하고 언제 응급실에 오는지 |

### movement → 파킨슨병 (15개)

| id | 항목 | 해당하는 것 |
|---|---|---|
| `motor` | 운동 증상 | 떨림, 느려짐, 뻣뻣함, 보행·자세 이상 |
| `onset_side` | 시작 부위·시기·진행 | 어느 쪽에서 언제 시작해 어떻게 진행했는지 |
| `med_response` | 약 효과 | 레보도파 등 약을 먹으면 좋아지는지 |
| `fluctuation` | 약효 변동 | 약효가 빨리 떨어지는지, 좋을 때와 나쁠 때의 변동 |
| `dyskinesia` | 이상운동증 | 약 먹은 뒤 몸이 저절로 움직이는지 |
| `falls_freezing` | 낙상·보행 동결 | 넘어짐, 발이 붙는 느낌 |
| `cognition_psychosis` | 인지 저하·환각 | 기억력 저하, 헛것이 보임, 망상 |
| `mood_sleep` | 기분·수면 | 우울, 불안, 잠꼬대·꿈 행동, 낮 졸림 |
| `autonomic` | 자율신경 증상 | 일어설 때 어지럼, 변비, 소변 문제 |
| `swallow_speech` | 삼킴·말하기 | 사레, 목소리 작아짐, 발음 |
| `impulse_control` | 충동조절 문제 | 도박, 쇼핑, 과식 등 충동 행동 (해당 약 복용 시) |
| `med_plan` | 약 계획 | 약 종류·용량·복용 시간 변경 |
| `atypical` | 비전형 소견 | 초기 낙상, 빠른 진행, 약에 반응 없음 등 다른 질환을 의심할 소견 |
| `exercise_rehab` | 운동·재활 | 운동, 재활 치료 권유 |
| `function_caregiver` | 일상 기능·보호자 | 혼자 할 수 있는 일, 보호자 도움 |

### cognitive → 치매 (14개)

| id | 항목 | 해당하는 것 |
|---|---|---|
| `onset_course` | 시작 시기·진행 양상 | 언제부터, 서서히·갑자기·계단식으로 나빠졌는지 |
| `memory` | 기억력 저하 양상 | 최근 일을 잊음, 같은 말 반복 등 |
| `other_domains` | 다른 인지 영역 | 말하기, 길 찾기, 계산, 계획·판단 |
| `daily_function` | 일상생활 수행 | 약·돈 관리, 운전, 혼자 외출, 집안일 |
| `behavior` | 행동·정신 증상 | 망상, 환각, 배회, 공격성, 우울, 무관심 |
| `cognitive_test` | 인지 검사 | 선별 검사나 신경심리검사 시행·결과 |
| `reversible_workup` | 가역적 원인 검사 | 갑상선, 비타민, 혈액검사 등 고칠 수 있는 원인 확인 |
| `imaging` | 뇌 영상 | MRI 등 계획 또는 결과 |
| `med_review` | 인지에 영향 주는 약 검토 | 수면제, 항콜린제 등 복용 약 확인 |
| `treatment` | 인지 개선제 | 약 시작·변경·부작용 |
| `differential` | 감별 소견 | 환시, 꿈 행동, 파킨슨 증상, 성격 변화 등 |
| `safety` | 안전 | 운전, 가스·불, 낙상, 길 잃음 |
| `caregiver` | 보호자 부담·돌봄 | 보호자 부담, 돌봄 계획, 지원 제도 |
| `future_planning` | 향후 계획 | 대리 결정, 연명의료, 장기 요양 |

### spine → radiculopathy (14개)

| id | 항목 | 해당하는 것 |
|---|---|---|
| `pain_distribution` | 통증·저림 부위와 방사 | 어디가 아프고 저린지, 팔·다리로 뻗치는지, 어느 쪽인지 |
| `onset_course` | 시작·유발 동작·경과 | 언제, 무엇을 하다 시작했고 어떻게 변했는지 |
| `weakness` | 근력 저하 | 힘이 빠지는 부위 |
| `sensory` | 감각 저하 | 감각이 무딘 부위 |
| `reflex` | 반사 검사 | 힘줄 반사 검사 결과 |
| `provocative_test` | 유발 검사 | 다리 들어 올리기, 목 젖히기 등으로 통증이 재현되는지 |
| `bowel_bladder` | 대소변 장애·회음부 감각 | 소변·대변 문제, 엉덩이·회음부 감각 저하 |
| `myelopathy` | 척수 압박 징후 | 보행 장애, 손 기능 저하, 양쪽 증상 |
| `red_flags` | 위험 신호 | 암 병력, 발열, 체중 감소, 외상, 밤에 심한 통증 |
| `imaging` | 영상 검사 | MRI 등 계획 또는 결과 |
| `electrodiagnosis` | 신경전도·근전도 검사 | 검사 계획 또는 결과 |
| `conservative` | 보존 치료 | 약, 물리치료, 운동, 자세 |
| `intervention` | 주사·수술 기준 | 주사 치료나 수술을 고려하는 경우와 의뢰 |
| `return_precautions` | 다시 와야 할 증상 | 어떤 증상이 생기면 바로 와야 하는지 |

## 측정 1 (gpt-4o, REPEAT=3)과 채점 수정

- context_only 누출이 ER 3, ICU 3으로 나왔지만 실제 누출이 아니었다. 화면에 "언급 안 됨"으로
  보여 주는 목록 label("정맥 혈전용해제 결정", "뇌파")을 채점기가 모델 출력으로 읽었다.
- 녹음 내용 recall(ER 75%, ICU 93%)도 부풀려졌다. frame_checks의 근거 구절은 대화를 그대로
  옮긴 것이라 키워드가 들어 있다.
- 수정: frame_checks 칸은 어떤 등급의 채점에도 쓰지 않는다. 어디서 찾았는지 표시만 한다.
- `make diagnose-structure`가 저장된 출력을 현재 채점기로 다시 채점한다(recall, 누출). API를
  다시 부르지 않는다.
- 항목별 결과는 3번 실행에서 모두 같았다(temperature 0). 맞는지는 의료진 판단이 필요하다.

| ER (stroke) 언급됨 3/3 | ER 언급됨 0/3 |
|---|---|
| deficit, vessel_occlusion, core_perfusion, thrombectomy, antithrombotic_plan, etiology_workup, worsening, disposition, procedure_consent | onset_time, hemorrhage, thrombolysis, prior_antithrombotic, blood_pressure, swallow |

| ICU (seizure) 언급됨 3/3 | ICU 언급됨 0/3 |
|---|---|
| provoking, acute_treatment, airway, labs, cause | semiology, duration_count, recovery, history, adherence, imaging, eeg, asm_plan, safety, rescue |

- 지연: ER 26.9s, ICU 24.0s. frame_checklist 호출은 3.6-3.8s다.

# Task 09: 의료진 정답(gold) 대비 핵심 구조화 평가

## 배경 (사용자 요청, 2026-10-09)

ICU 보호자 상태설명 역할극 녹음(5분 31초)의 답안 전사와 의료진이 기대하는
핵심 구조를 받았다. 기대 구조는 다음과 같다.

- status epilepticus로 intubation 후 midazolam infusion 중
- EEG 결과로 ASM 추가
- r/o SCMP로 CAG 필요성을 당직 cardio staff에게 확인했고, 시술은 하지 않음
- 조영제로 인한 r/o CIN으로 dialysis가 필요할 수 있음
- 연명의료 중단 여부를 미리 고민해야 함

이런 구조를 화자분리 이후 자동으로 만들 수 있는지 측정하고자 한다.

## 핵심 발견: 기대 구조의 일부는 녹음에 없다

답안 전사(43줄)와 기대 구조를 대조한 결과(`make eval-structure`의 gold
자체 검증으로 확인):

| 기대 항목 | 녹음에서 실제로 한 말 | 등급 |
|---|---|---|
| 발작, 당 조절 불량 | "당이 안좋아서 발작이 온거고" | conversation |
| 항발작제, 진정 | "항 발작제를 지금 투여해서 재워놨어요" | conversation |
| 기관삽관 | "목에 관 박아놨잖아요", "기관삽관을 유지하거나" | conversation |
| 심장 이상, 관상동맥 평가 | "심장 뛰는 모양이 이상", "관상동맥 … 보는게 중요" | conversation |
| 응급 시술 안 함 | "응급하게 시술을 할 것은 아니다" | conversation |
| 조영제와 콩팥, 투석 가능, 평생 | 명시함 | conversation |
| 가래 증가로 약 증량 | 명시함 (기대 구조에는 없던 항목) | conversation |
| 연명의료, 가족 상의 | 명시함 | conversation |
| 보호자: 당뇨약 잘 먹음, 투석 전단계 들음 | 보호자 발화 | conversation |
| status epilepticus, midazolam, EEG, SCMP, CAG, 당직 cardio, CIN | **말하지 않음** | context_only |

- 녹음에서는 관상동맥 평가를 "CT를 찍어야 하는데 조영제"라고 설명했다.
  기대 구조의 CAG와 다르므로, 구조화 결과는 녹음대로 CT로 남겨야 한다.
- CLAUDE.md("입력에 없는 진단·약물·용량·수치·날짜를 생성하지 않는다")에 따라
  context_only 항목이 전사만으로 생성되면 hallucination이다. 이 평가는
  그 항목을 **누출(leak)**로 센다.
- 기대 구조를 그대로 얻으려면 전사 외에 **의료진이 제공하는 맥락 입력**이
  필요하다(예: EMR 문제목록 붙여넣기 또는 짧은 구술 요약). 이것은 제품 기능
  결정이므로 이번 범위에서 구현하지 않는다.

## In scope

- `scripts/answer_to_transcript.py`: 손으로 친 답안을 `<stem>.transcript.json`으로
  변환한다. 콜론 없는 화자 전환은 모두 경고하고, `SPEAKERS=`로 화자를 제한한다.
- `app/eval/structure_eval.py`: 각 gold 항목이 출력의 한 항목과 맞는지 판정하고,
  context_only 누출과 gold 자체 오류를 검사한다. 한글은 띄어쓰기를 무시하고,
  영문 약어는 단어 경계 기준으로 비교한다("CIN"이 "medicine"에 매칭되지 않음).
- `scripts/eval_structure_against_gold.py`: 앱의 enrichment와 structure 단계를
  그대로 돌려 채점하고 단계별 지연을 잰다. 기본은 mock이고, `REAL=1`이면 OpenAI를 쓴다.

## Out of scope

- 의료진 맥락 입력 기능과 프롬프트 변경
- 구조 스키마 확장(시행한 치료, 연명의료/goals of care, 보호자 이해·요청 칸)
- ASR 전사를 넣는 end-to-end 실행(같은 스크립트에 ASR 출력을 넣으면 되지만,
  사용자 장비에서 실행해야 함)

## Gold 형식

`data/annotations/<case>.gold.json` (gitignore 대상)

```json
{"case": "sim_icu_01",
 "items": [{"id": "plan_possible_dialysis", "section": "plan", "tier": "conversation",
            "must_match": [["투석"], ["할수도", "가능"]]}]}
```

`must_match`는 OR 목록들의 AND다. 출력의 **한 항목** 안에서 모든 그룹이
만족돼야 맞은 것으로 센다.

## 결과 (이 샌드박스)

- ICU gold 25개(conversation 18개, context_only 7개)의 자체 검증을 통과했다.
- mock은 전사를 그대로 복사하므로 recall 100%, 누출 0이다. 이 수치는 품질 점수가
  아니라 gold가 입력에서 도달 가능하다는 확인일 뿐이다.
- 실제 LLM 측정은 OpenAI 키가 없어 하지 못했다. 사용자 장비에서 `REAL=1`로 실행해야 한다.

## Tests

- `test_structure_eval.py`(7): 띄어쓰기와 단어 경계, 한 항목 안 AND 조건,
  recall과 section, 누출, gold 자체 검증, 답안 화자 파싱과 경고

## 남은 위험

- 키워드 매칭은 의미 판정이 아니다. "투석은 필요 없다"도 [["투석"], ["필요"]]
  형태의 gold에는 맞을 수 있다. 부정 표현이 중요한 항목은 대안어를 좁게 잡고,
  최종 판정은 의료진이 출력을 직접 읽어서 한다.
- 녹음 1건 기준이다. ER 답안이 오면 같은 형식으로 gold를 추가한다.

## 추가 (2026-10-10): ER 답안

ER 녹음(13분 15초 = 첫 녹음 6분 1초 + 두 번째 녹음)의 답안 177줄을 반영했다.

- 변환기 확장:
  - 번호 붙은 화자: `의사 1`, `의사2`, `간호사 2`
  - `발화자 N`은 역할을 모르는 화자로 두고, `ALIASES=`로 이름을 붙인다
  - `noise:`는 배경 화자(BG)로 둔다
  - `(mm:ss)`는 `approx_start`로 옮긴다
  - `-- … N분 M초` 주석은 이후 시간에 더할 오프셋으로 쓴다
- 새 등급 `must_exclude`: 입력에는 있지만 요약에 나오면 안 되는 것(배경 대화,
  욕설 등). 출력에 나오면 누출로 센다.
- 평가 스크립트는 배경 구간을 기본으로 입력에서 뺀다(역할 확인 단계에서
  "배경"으로 지정하는 흐름과 같음). `INCLUDE_BACKGROUND=1`이면 배경까지 넣고 시험한다.
- ER gold는 **답안을 바탕으로 만든 초안**이다(conversation 30, context_only 5,
  must_exclude 2). 의료진 검토가 필요하다. context_only에는 PFO, TEE, NIHSS,
  thrombectomy(용어), tPA를 넣었다. 녹음에서는 "심장 그 구멍", "내시경 초음파",
  "혈전을 끄집어내는 시술"이라고만 말했다.
- mock 실행 결과: gold 자체 검증을 통과했다. 의사의 욕설은 must_exclude 누출로 잡히고,
  `INCLUDE_BACKGROUND=1`이면 배경 대화도 누출로 잡힌다. mock은 전사를 그대로
  복사하므로 이 결과는 예상대로이며, 실제 LLM이 이를 걸러내는지가 측정 대상이다.

## 추가 (2026-10-10): 진료 틀(frame)과 의사 검수 체크리스트

사용자 결정:

- 용어 변환은 의료진이 고른 큰 틀(seizure, stroke)이 있을 때만 허용한다.
- 부정 표현(예: "clopi loading 안 함")은 의사가 직접 검수한다.

변경 내용:

- 새 등급 `frame_term`과 항목 필드 `"frame"`. `FRAMES=stroke`로 채점하면 그 틀의
  용어는 기대 항목(frame-term recall)이 되고, 틀을 지정하지 않았는데 나오면
  누출(frame-term leak)이다.
- gold 항목의 `note`는 의사 검수 체크리스트로 출력한다.
- ER gold에 사용자 핵심 구조를 반영했다: EVT 여부 고민, 결정의 어려움과
  위험·이득 판단, perfusion이 버티는 소견, 운동 검사, argatroban(의사 2와 상의),
  clopi loading 안 함. NIHSS, EVT, PFO, TEE는 `frame_term`(stroke)으로 옮겼다.
  tPA는 녹음에서 언급되지 않아 context_only로 남겼다.
- ICU gold: status epilepticus와 ASM을 `frame_term`(seizure)으로 옮겼다.
  midazolam, EEG, SCMP, CAG, CIN, 당직 cardio는 틀만으로는 알 수 없어
  context_only로 남겼다.
- 파이프라인은 아직 진료 틀을 입력으로 받지 않는다. 지금의 frame-term recall은
  기능을 넣기 전 기준선이다.

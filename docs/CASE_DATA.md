# 녹음 케이스 데이터 (tasks/16)

녹음 1건을 케이스 폴더 하나로 관리한다. 폴더 이름은 가상의 환자 매칭 번호다.
이 폴더는 전부 gitignore된 `apps/api/data/` 아래에 있고 **절대 커밋하지 않는다**.

## 이번 단계에서 EMR의 용도

- **정답지(gold) 개선 참고 자료**와 **녹음 시점 메타데이터**로만 쓴다.
- 앱, 평가 스크립트, LLM 호출 어느 것도 `*.emr.txt`를 읽지 않는다.
- "차트 맥락 입력"(EMR을 LLM에 넣는 것)은 이번 단계에 없다.

## 폴더 구조

```
apps/api/data/cases/
  er_3023432/
    er_3023432.wma              원본 녹음 (어떤 형식이든)
    er_3023432.opus             make prepare-case-audio 로 생성 (모노 16 kHz)
    er_3023432.answer.txt       의사가 쓴 답안 전사 (기존과 같은 형식)
    er_3023432.transcript.json  make answer-to-transcript 로 생성
    er_3023432.emr.txt          익명화한 기록지 (선택, 정답지 참고용)
    er_3023432.meta.json        케이스 정보 (아래)
    er_3023432.openai_gpt-4o.run1.output.json  평가 출력 (자동)
```

- 폴더 이름: `<er|icu|ward|opd>_<번호>`. 그 안의 파일은 모두 같은 이름으로 시작한다.
- 정답지는 지금처럼 repo의 `tests/evals/gold/`에 둔다(키워드만, 본문 없음).

## meta.json

```json
{
  "case": "er_3023432",
  "setting": "er",
  "frame": "stroke",
  "split": "eval",
  "recorded_at": "D0 응급실 도착 +2h, non-contrast CT 후, 시술 결정 전",
  "speakers": ["의사1", "의사2", "보호자(딸)"],
  "emr_scope": "응급실 초진, 신경과 협진 기록 D0",
  "gold_case": "sim_er_01",
  "notes": ""
}
```

| 필드 | 뜻 |
|---|---|
| `case` | 폴더 이름과 같게 |
| `setting` | er / icu / ward / opd |
| `frame` | 평가할 진료 틀 (stroke, seizure, movement, cognitive, spine, neuromuscular ...) |
| `split` | dev(어휘에 말투를 옮겨도 됨) / eval(점수만 잼) |
| `recorded_at` | **상대 시점**만. 실제 날짜·시각 금지 (D0, HD#3, 도착 +2h, CT 후 등) |
| `emr_scope` | 기록지가 어느 범위인지 (선택) |
| `gold_case` | 이미 있는 정답지 이름을 계속 쓸 때 (기존 3건) |

## 익명화 (emr.txt, answer.txt, meta.json)

지울 것: 이름(환자·보호자·의료진), 등록번호, 주민번호·생년월일, 주소, 연락처, 실제 날짜,
병동·병상 번호, 이메일. 날짜는 D0 / D+1 / HD#2 같은 상대 시점으로 바꾼다.

`make check-cases`가 주민번호, 전화번호, 날짜, 7자리 이상 숫자, 이메일, "성명:" 같은 칸을
**줄 번호로만** 알려 준다. 사람 이름은 기계로 찾지 못하니 직접 확인한다.

## 처음 한 번: 기존 녹음 3건 옮기기

```bash
# 1) 지금 파일이 어디 있는지 확인
ls apps/api/data/annotations/
find . -path ./node_modules -prune -o -path ./apps/web/node_modules -prune -o \
  \( -name "*.opus" -o -name "*.m4a" -o -name "*.wav" -o -name "*.wma" \) -print

# 2) 새 번호로 옮기기 (번호는 직접 정한 가상 번호)
make migrate-case OLD=sim_er_01  NEW=er_<번호>
make migrate-case OLD=sim_icu_01 NEW=icu_<번호>
make migrate-case OLD=sim_mg_01  NEW=icu_<번호>   # MG 녹음을 찍은 곳에 맞게 er/icu/ward
```

`migrate-case`는 `<OLD>.*` 파일을 `cases/<NEW>/<NEW>.*`로 옮기고, 기존 정답지를 계속 쓰도록
`gold_case`가 들어간 meta.json을 만든다. frame, split, recorded_at은 직접 채운다.
(`<번호>`는 실제 숫자로 바꿔서 입력한다.)

## 새 녹음 추가

```bash
N=er_3023432                                  # 가상 매칭 번호
mkdir -p apps/api/data/cases/$N
cp <녹음 파일 경로> apps/api/data/cases/$N/$N.wma
make prepare-case-audio CASE=$N               # -> $N.opus
# $N.answer.txt, $N.meta.json, (선택) $N.emr.txt 작성
make answer-to-transcript ANSWER=apps/api/data/cases/$N/$N.answer.txt
make check-cases CASE=$N
```

## 평가

```bash
make eval-structure CASE=er_3023432 REAL=1 REPEAT=3   # transcript, gold, frame을 폴더에서 찾음
make diagnose-structure CASE=er_3023432
make check-vocab-leakage                              # 케이스 폴더의 eval 전사도 확인
```

## EMR로 정답지 고치기 (사람이 하는 일)

기록지의 중요 사실마다 아래처럼 나눈다.

| 기록지 사실이 대화에서 | 정답지 등급 | 키워드 |
|---|---|---|
| 말해졌다 | `conversation` | **대화에서 쓴 말**로 (예: "피 검사가 안 좋다") |
| 말해지지 않았다 (차트에만) | `context_only` | 차트 용어로 (예: "midazolam", "EEG"). 요약에 나오면 누출 |
| 일상어로 말해졌고 진료 틀 용어가 있다 | `frame_term` | 용어로 (예: "EVT") |
| 질환 필수 항목을 다뤘는지 | `frame_checks` | mentioned / not_mentioned |

정답지 수정은 키워드와 등급만 알려 주면 된다. 기록지 본문을 채팅에 붙여 넣지 않는다.

# Clinician gold for structuring evals (tasks/09)

판정 키워드만 담은 파일이다. 대화 원문, 환자 이름, 음성은 넣지 않는다.
답안 전사(`*.answer.txt`), 변환 전사(`*.transcript.json`), LLM 출력은 gitignore된
`data/` 아래에만 둔다.

```bash
make eval-structure TRANSCRIPT=<data 아래 transcript.json> GOLD=tests/evals/gold/sim_er_01.gold.json REAL=1 FRAMES=stroke
```

등급(tier)의 뜻은 `apps/api/app/eval/structure_eval.py`의 docstring을 본다.

## 새 녹음 추가하기 (tasks/11)

녹음 1건마다 세 가지를 준비한다:

1. 음성 파일 (역할극, 실제 환자 정보 없음)
2. 답안 전사 (`의사:`, `보호자:`, `noise:` 형식. 시간 표기 `(mm:ss)`는 있으면 좋음)
3. 핵심 구조 몇 줄 (주 상병, 시행한 것, 결정, 계획 등. 의료진이 기대하는 요약)

어휘용(`dev`)과 평가용(`eval`)은 녹음 단위로 나눈다.

- `dev`: 실제 말투를 어휘(`prompts/frames/`)에 옮겨도 되는 녹음
- `eval`: 어휘를 만들 때 절대 보지 않고 점수만 재는 녹음

진료 틀마다 번갈아 배정한다(1번째 dev, 2번째 eval, …). gold 파일의 `"split"`에
적고, 어휘를 고친 뒤에는 `make check-vocab-leakage`로 확인한다.

## 질환별 필수 확인 항목 정답 (tasks/14, 선택)

진료 틀에 필수 확인 목록(`prompts/frame_checks/<frame>.json`)이 있으면, 평가 출력에 항목마다
"언급됨" 횟수가 나온다. 의료진이 대화를 듣고 항목별 정답을 gold에 적으면 일치율도 나온다.

```json
"frame_checks": {
  "stroke": {"onset_time": "mentioned", "swallow": "not_mentioned"}
}
```

- 항목 id는 `prompts/frame_checks/<frame>.json`의 `id`를 그대로 쓴다. 적지 않은 항목은 채점하지 않는다.
- `mentioned`: 대화에서 그 항목을 다룸(물어보기만 했거나 정상이라고 한 것도 포함). `not_mentioned`: 다루지 않음.

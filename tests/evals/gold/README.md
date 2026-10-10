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

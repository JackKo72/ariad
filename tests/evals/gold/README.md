# Clinician gold for structuring evals (tasks/09)

판정 키워드만 담은 파일이다. 대화 원문, 환자 이름, 음성은 넣지 않는다.
답안 전사(`*.answer.txt`), 변환 전사(`*.transcript.json`), LLM 출력은 gitignore된
`data/` 아래에만 둔다.

```bash
make eval-structure TRANSCRIPT=<data 아래 transcript.json> GOLD=tests/evals/gold/sim_er_01.gold.json REAL=1 FRAMES=stroke
```

등급(tier)의 뜻은 `apps/api/app/eval/structure_eval.py`의 docstring을 본다.

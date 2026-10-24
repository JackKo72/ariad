# ARIAD 2단계 로컬 실행 가이드

2단계(생활습관 실행계획·이행 판정·미시행 사유·외래 전 리포트) 코드를 로컬에서 확인하는 순서. 모든 데이터는 합성이다.

## 0. 코드 받기

```bash
git fetch origin
git checkout claude/sharp-goldberg-leijbj        # 처음 한 번
git pull --ff-only origin claude/sharp-goldberg-leijbj   # 이후 갱신
```

`git pull`이 "divergent branches"로 실패하면 다른 브랜치(main 등)에 서 있는 것이다. `git branch --show-current`로 확인하고 위 checkout부터 다시 한다.

## 1. 설치 (처음 한 번)

```bash
make setup        # apps/api/.venv 생성 + requirements-dev.txt(PyYAML 포함) + 웹 의존성
make doctor       # 도구 확인
```

## 2. API 키 없이 돌려보기 (mock, 외부 호출 없음)

| 목적 | 명령 | 기대 결과 |
| --- | --- | --- |
| 전체 테스트 | `make test` (또는 `apps/api/.venv/bin/python -m pytest -q`) | 전부 passed |
| 카탈로그 TODO 목록 | `apps/api/.venv/bin/python tests/test_catalog.py` | 의료진이 채울 값 15개 |
| 지시 추출 평가 (20건) | `apps/api/.venv/bin/python scripts/eval_action_directives.py` | 정밀도·재현율 표 |
| 사유 분류·red flag 평가 | `apps/api/.venv/bin/python scripts/eval_barriers.py` | red flag 10/10, 혼동행렬 |
| 시나리오 A–D 4주 시뮬레이션 | `make sim` | `sim/output/scenario_*.md` 리포트 4개 |
| 위 평가 한 번에 | `make eval` | 1단계 eval + 2단계 eval 3개 |

mock 수치는 "연결이 된다"는 확인일 뿐 품질 근거가 아니다 (키워드 규칙 + 같은 사람이 쓴 라벨).

## 3. 실제 LLM으로 평가 (provider 모드)

1. `apps/api/.env.local` 작성 (git에 안 올라감, README "텍스트 LLM" 절 참고):
   ```
   OPENAI_API_KEY=sk-...
   OPENAI_TEXT_MODEL=gpt-4o-mini
   ```
2. 실행:
   ```bash
   make eval-provider
   ```
   - `scripts/eval_action_directives.py` → 지시 추출·카탈로그 매칭 정밀도/재현율, 동의 정도 정확도
   - `scripts/eval_barriers.py` → red flag 탐지(규칙이라 mock과 같아야 함) + 사유 분류 혼동행렬
   - `sim/run_scenarios.py` → 시나리오 리포트를 `sim/output_provider/`에 저장 (gitignore)
   - JSON 결과: `sim/output_provider_directives.json`, `sim/output_provider_barriers.json`
3. 볼 것:
   - 지시 추출 code P/R과 `needs_review` 비율
   - 사유 분류 정확도, 확인 질문(follow-up) 비율, `?`(분류 안 됨) 건수
   - 시나리오 리포트 상단 `<!-- 승인에서 제외된 항목 -->` (실제 LLM이 다른 지시를 뽑았거나 목표가 비어 있으면 여기 나온다)
   - `sim/output/`(mock)과 `sim/output_provider/` 비교

API 호출은 합성 대화·합성 응답만 보낸다. 실제 환자 데이터로 돌리지 않는다.

## 4. 의료진 검토 → 반영

`docs/clinician_review.md`가 결정할 항목 전체 목록이다 (카탈로그 수치, 판정 규칙, 환자 문구, red flag, 리포트 문구, 평가 라벨, 설계 충돌 결정).

1. 값 결정 → 해당 YAML 수정 (`catalog/actions.yaml`, `catalog/questions.yaml`, `config/*.yaml`)
2. 검토 끝난 파일은 `review_status: clinician_reviewed`
3. 평가 라벨 수정 → `tests/fixtures/visits/*.json`, `tests/fixtures/barriers/*.json`의 `label_status: clinician_reviewed`
4. `make test && make eval && make sim` → `git diff sim/output`으로 리포트 변화 확인

## 5. 파일 지도

| 단계 | 코드 | 설정·데이터 | 테스트 |
| --- | --- | --- | --- |
| 1단계 확장 (지시 추출) | `app/pipeline/segments.py`, `structure.py`, `directive_validation.py` | `prompts/structure_transcript.md` 0.2.0 | `test_action_directives.py`, `tests/integration/test_action_directives.py` |
| 카탈로그·스키마 | `app/domain/stage2.py`, `app/stage2/catalog.py` | `catalog/actions.yaml`, `packages/contracts/schema/stage2/` | `tests/test_catalog.py`, `test_stage2_schemas.py` |
| 정규화 | `app/stage2/normalizer.py` | `prompts/classify_action_directive.md` | `test_stage2_normalizer.py` |
| 체크인·판정 | `app/stage2/checkin.py`, `judge.py` | `catalog/questions.yaml`, `config/checkin.yaml`, `config/judge.yaml` | `test_stage2_checkin.py`, `test_stage2_judge.py` |
| 사유·red flag | `app/stage2/barrier.py` | `config/red_flags.yaml`, `config/barrier.yaml`, `prompts/classify_barrier.md` | `test_stage2_barrier.py` |
| 리포트 | `app/stage2/report.py` | `config/report.yaml` | `test_stage2_report.py` |
| 시뮬레이션 | `sim/run_scenarios.py` | `sim/scenarios.yaml` | `test_sim_scenarios.py` |

(`app/...`는 `apps/api/app/...`, 테스트는 따로 적지 않으면 `apps/api/tests/`.)

## 6. 아직 없는 것

2단계 기능은 라이브러리 함수까지만 있다. ActionPlan·CheckIn·BarrierReport를 저장하는 DB 테이블, API endpoint, 화면, 실제 메시지·알림 발송은 없다.

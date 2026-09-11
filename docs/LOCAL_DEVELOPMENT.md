# Local Development Workflow

## 1. Install once

권장 도구는 Git, Node LTS, Python 3.12, ffmpeg다. Docker는 선택사항이며 첫 vertical slice에는 필수가 아니다. 실제 버전은 저장소의 `.tool-versions` 또는 동등한 파일로 고정한다.

코딩 에이전트에게 다음을 구현하도록 요청한다.

- `make doctor`: 설치 여부와 버전 확인
- `.env.example`: 비밀값 없는 환경변수 목록
- mock이 기본인 `make dev`
- 한 명령으로 실행되는 test/eval

## 2. Environment modes

```text
ARIAD_MODE=mock       # 기본: 외부 API 없음, 합성 데이터만
ARIAD_MODE=provider   # 실제 ASR/LLM sandbox 테스트
DEBUG_ARTIFACTS=true # 로컬+합성 데이터에서만 허용
```

API key는 `.env.local` 또는 OS secret store에 두고 Git에 commit하지 않는다. Frontend 환경변수로 provider secret을 전달하지 않는다.

## 3. First build sequence

### Phase A: scaffold

1. 빈 repo에서 문서 구조를 배치한다.
2. `tasks/01_VERTICAL_SLICE.md`를 지정하고 계획만 요청한다.
3. stack과 폴더, 실행 명령을 확정한다.
4. mock mode로 FE/API를 실행한다.

### Phase B: vertical slice

1. 합성 전사 입력
2. mock structure/explanation 반환
3. 의료진 수정
4. 승인 version 생성
5. public mobile view
6. 승인 전 접근차단 E2E

### Phase C: audio pipeline

`tasks/02_AUDIO_PIPELINE.md`를 실행한다. 먼저 고정 fixture와 mock provider로 stage 저장/replay를 완성한 뒤 실제 provider를 하나씩 연결한다.

### Phase D: provider test

1. 3개의 합성 짧은 파일만 사용한다.
2. API key와 provider mode를 로컬에서 켠다.
3. ASR만 실제로 연결하고 나머지는 mock으로 둔다.
4. stage output, latency, cost, error를 확인한다.
5. 다음에 diarization, 마지막에 LLM을 연결한다.
6. 전체 golden set 실행 전 작은 표본으로 비용과 실패를 확인한다.

## 4. Daily agent loop

```text
작은 task 작성
→ 관련 docs를 지정해 계획 요청
→ 계획 검토
→ 구현 요청
→ 에이전트가 test 실행
→ 사람이 브라우저와 git diff 확인
→ regression test 확인
→ commit
```

한 세션에 여러 핵심 기능을 섞지 않는다. 새 기능과 대규모 refactor도 같은 task에 넣지 않는다.

## 5. Local verification checklist

```bash
make doctor
make setup
make dev
make test
make e2e
make eval
make lint
git diff --check
git status --short
```

`make dev` 후 최소한 다음을 직접 확인한다.

- 합성 면담을 만들 수 있다.
- 처리단계와 실패단계가 보인다.
- 새로고침 후 draft가 남는다.
- 승인 전 public URL은 거절된다.
- 승인 후 정확한 version만 보인다.
- 승인 후 수정하면 기존 공개본은 변하지 않는다.
- 모바일 너비에서 읽을 수 있다.

## 6. Debug request to coding agent

```text
docs/DEBUGGING.md와 docs/TESTING_AND_EVALS.md를 읽어줘.
아래 합성 fixture의 실패를 재현하고 최초로 잘못된 pipeline stage를 찾아줘.

- fixture: [경로]
- pipeline_run_id: [ID]
- expected: [기대값]
- actual: [실제값]

아직 수정하지 말고 다음만 보고해.
1. 재현 명령과 결과
2. 최초 실패 stage
3. 가장 가능성 높은 원인
4. 최소 수정안
5. 추가할 regression test
```

원인을 확인한 다음에만 수정하도록 요청한다.

```text
위 최소 수정안만 구현해줘. 범위를 넓히지 말고 regression test를 먼저 추가해.
관련 test와 eval을 실행하고 변경 전후 결과를 비교해줘.
```

## 7. When to move beyond local MVP

다음이 확인되기 전에는 production infrastructure를 늘리지 않는다.

- 긴 오디오 때문에 API process가 실제로 불안정함
- 동시처리 요구량이 측정됨
- 병원 보안·망·저장정책이 확정됨
- 합성 eval과 의료진 검토 workflow가 통과함


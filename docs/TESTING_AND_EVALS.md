# Testing and AI Evaluation

## 1. Two different kinds of correctness

일반 software test와 AI quality eval을 분리한다.

- Test: 상태전이, API schema, 권한, 저장, 화면 동작이 결정적으로 맞는가?
- Eval: 전사·화자분리·구조화·쉬운 설명의 품질이 기준을 충족하는가?

## 2. Required layers

| Layer | 예시 | 실행 시점 |
|---|---|---|
| Unit | 상태전이, role mapping rule, validator | 매 변경 |
| Contract | provider mock과 JSON schema | 매 변경 |
| Integration | API+DB, 승인/공개 권한 | 매 변경 |
| E2E | 등록→처리→수정→승인→모바일 공개 | 주요 기능 |
| Eval | 합성 대화 golden set batch | prompt/provider/pipeline 변경 |

## 3. Synthetic golden set

처음에는 20~30개의 짧은 한국어 합성 면담을 만든다.

- 의사 1명+환자 1명
- 의사+환자+보호자
- 겹친 발화와 짧은 맞장구
- 생활소음과 병실소음
- 약명, mg, 횟수, 날짜, 검사수치
- 부정 표현: “복용하지 않았다”
- 불확실 표현: “아마”, “확인해 보겠다”
- 서로 모순되는 정정 발화

각 fixture에는 정답 transcript, speaker turns, roles, clinical JSON, 허용 patient explanation facts를 둔다. 실제 환자 대화는 넣지 않는다.

## 4. Metrics

| Stage | 주요 지표 |
|---|---|
| ASR | Korean CER, 약명/수치 exact match |
| Diarization | DER, speaker confusion, overlap recall |
| Role assignment | doctor/patient/guardian accuracy, uncertain recall |
| Structure | field precision/recall, critical omission, numeric match |
| Simplification | unsupported claim, preserved warnings, clinician edit distance |
| Product | review time, pipeline latency, provider cost, failure rate |

한국어 전사는 WER보다 CER를 우선 기록한다. 읽기 쉬움은 자동 점수 하나로 통과시키지 말고 환자/의료진 평가 rubric을 병행한다.

## 5. Non-negotiable release gates

- 승인되지 않은 설명의 public 접근 테스트 통과율 100%
- 합성 eval에서 근거 없는 중요 진단·약물·용량·검사수치 0건
- 모든 숫자와 약물 필드에 source span 또는 `needs_confirmation`
- role confidence가 낮은 경우 자동 공개 불가
- 실패한 pipeline stage와 version을 재현 가능

나머지 품질 threshold는 첫 baseline을 측정한 뒤 `docs/DECISIONS.md`에 수치와 근거를 기록한다. 임의의 높은 숫자를 먼저 약속하지 않는다.

## 6. Standard local commands to implement

코딩 에이전트는 프로젝트에 아래 명령을 제공해야 한다.

```bash
make doctor        # 필수 도구와 환경 확인
make setup         # 의존성 설치
make dev           # web/api 실행
make test          # unit+contract+integration
make e2e           # 브라우저 흐름
make eval          # synthetic golden set 평가
make lint          # format/lint/typecheck
```

명령이 실패하면 성공으로 보고하지 말고 원인과 재현 명령을 남긴다.


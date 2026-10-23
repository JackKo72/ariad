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

tasks/06_ASR_OUTPUT_VERIFICATION.md: 기존 "약명/수치 exact match"(네 가지 고정 anchor의 PASS/FAIL)만으로는 anchor가 짚지 않은 구간의 회귀를 못 잡는다. `app/eval/asr_metrics.py`(표준 편집거리 기반 `compute_cer`/`compute_wer`, 순수 함수, 단위 테스트 있음)로 세그먼트별·전체 CER/WER을 숫자로 함께 기록한다(`scripts/compare_asr_accuracy.py`에 통합됨). CER가 여전히 우선 지표이고 WER는 참고용 — 한국어 ASR 띄어쓰기가 일정하지 않아 WER 단독으로는 판단하지 않는다.

화자분리 정확도: `app/eval/diarization_metrics.py`(frame 기반 DER, 0.25초 collar, role_purity, overlap recall)가 `scripts/compare_diarization_engines.py`에 연결되어 있다. `<audio>.transcript.json`이 있으면 속도와 함께 정확도를 채점한다.

의사 목소리 등록(평가 전용, 제품 pipeline 미적용 — PRODUCT.md의 생체 음성인식 제외 원칙 유지): `scripts/benchmark_doctor_enrollment.py` + `app/eval/doctor_enrollment.py`. 의사 voiceprint로 의사 군집을 찾고 작은 외부 군집을 오염으로 표시하는 방식을 doctor recall/precision, contamination kept, conversation dropped, similarity margin으로 채점한다. 실제 의사 음성·진료 녹음은 저장소에 넣지 않는다. 첫 합성 측정(2026-10-23, espeak 음성): 등록 의사 판별은 정확(진짜 0.87 vs 다른 의사 0.23)했지만 diarizer가 의사·환자를 한 군집으로 합쳐 군집 단위 판정의 한계가 드러났다. 합성 음성끼리는 실제 사람보다 서로 비슷하므로 실제 녹음으로 재측정해야 한다.

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


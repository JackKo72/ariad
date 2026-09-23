# Task 03: Speaker consolidation and latency optimization

## 0. Current context

Task 01과 Task 02가 구현되어 있다.

- 녹음된 음성파일을 업로드할 수 있다.
- ASR이 화자별 segment를 반환한다.
- transcript를 LLM에 보내 구조화 및 환자용 설명을 생성할 수 있다.
- 문제 1: 실제 사람 수보다 많은 speaker label이 생성되는 over-segmentation이 있다.
- 문제 2: 전체 처리시간이 너무 길지만 어느 단계가 병목인지 계측되지 않았다.

이번 task는 임의로 성능 최적화를 시작하지 않는다. 먼저 현재 pipeline을 계측하고 baseline을 만든 뒤, 정확도와 기존 승인 흐름을 보존하는 최소 수정만 구현한다.

## 1. Outcomes

### Speaker outcome

- 여러 raw speaker label을 하나의 canonical speaker로 수동 병합할 수 있다.
- 원본 ASR/diarization 결과는 수정하거나 삭제하지 않는다.
- 병합을 취소하거나 다시 나눌 수 있다.
- 선택적으로 speaker embedding을 이용해 병합 후보를 추천한다.
- 자동 추천은 의료진 확인 없이 확정되지 않는다.

### Performance outcome

- 한 pipeline run의 시간을 stage별로 확인할 수 있다.
- 동일 샘플의 cold/warm baseline과 최적화 후 결과를 비교할 수 있다.
- 반복 ASR/LLM 호출과 불필요한 오디오 변환을 제거한다.
- speaker 병합만 수정할 때 ASR을 다시 실행하지 않는다.
- 정확도와 안전성 회귀 없이 실제 wall-clock latency를 줄인다.

## 2. Read before editing

- `CLAUDE.md` 또는 `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/AI_PIPELINE.md`
- `docs/DEBUGGING.md`
- `docs/TESTING_AND_EVALS.md`
- `tasks/02_AUDIO_PIPELINE.md`
- 현재 audio upload, preprocessing, ASR, diarization, role assignment, LLM provider 코드
- 현재 DB schema와 pipeline stage 저장 방식

## 3. Important distinction

다음 세 개를 분리한다.

```text
raw speaker label: ASR provider가 반환한 A/B/C/...
canonical speaker: 병합 후 실제 인물에 가까운 speaker_1/2/3
clinical role: doctor/patient/guardian/unknown
```

`speaker A`와 `speaker C`가 같은 사람이라고 판단되어도 raw segment의 label은 보존한다. 별도 mapping으로만 표현한다.

```json
{
  "raw_to_canonical": {
    "A": "speaker_1",
    "B": "speaker_2",
    "C": "speaker_1"
  },
  "canonical_roles": {
    "speaker_1": "doctor",
    "speaker_2": "patient"
  },
  "version": 2
}
```

파형의 직접적인 모양이나 transcript 내용만으로 같은 사람이라고 결정하지 않는다. 동일 화자도 문장, 음량, 거리, 소음에 따라 waveform이 달라진다. 자동 병합에는 speaker embedding과 시간적 제약을 사용한다.

## 4. Phase 0: Inspect only

아직 코드를 수정하지 말고 다음을 조사한다.

1. audio upload부터 최종 draft까지 실제 function call graph
2. 동기/비동기 실행 여부
3. FFmpeg가 몇 번 실행되는지
4. 동일 음성파일이 몇 번 읽히고 업로드되는지
5. ASR API 호출 횟수와 model/config
6. LLM API 호출 횟수, 각 input/output token 수
7. role 수정 또는 재처리 시 ASR이 다시 실행되는지
8. 현재 cache 유무와 cache key
9. frontend가 어떤 방식으로 status를 polling하는지
10. provider client가 매 요청마다 새로 만들어지는지

결과를 다음 표로 보고한다.

| Stage | Code path | Runs per encounter | Blocking? | Repeated work risk |
|---|---|---:|---|---|

## 5. Phase 1: Latency instrumentation

최적화 전에 계측을 먼저 구현한다.

### Required identifiers

```text
request_id → encounter_id → pipeline_run_id → stage_run_id
```

### Required stage metrics

각 stage에 `time.perf_counter()`와 동등한 monotonic timer를 사용한다.

```text
upload
probe
preprocess
denoise
asr_network
asr_parse
speaker_mapping
speaker_embedding
structure_llm
explanation_llm
validation
database_write
total
```

각 stage record에는 다음만 포함한다.

- duration_ms
- status와 retry count
- audio_duration_seconds와 file_size_bytes
- provider/model/prompt/schema version
- input/output token count가 제공될 때의 token 수
- cache_hit 여부
- error code

audio/transcript/patient text/API key는 일반 log에 기록하지 않는다.

### Derived metrics

```text
real_time_factor = stage_duration_seconds / audio_duration_seconds
```

ASR, preprocessing, speaker embedding에 RTF를 계산한다.

### Benchmark command

다음 명령을 구현한다.

```bash
make benchmark-audio AUDIO=tests/fixtures/audio/sample_consultation.wav RUNS=3
```

결과는 cold run과 warm run을 구분하고 stage별 median, min, max, total을 표로 출력한다. 실제 patient content를 출력하지 않는다.

## 6. Phase 2: Manual speaker consolidation first

자동 clustering보다 먼저 신뢰할 수 있는 수동 병합을 구현한다.

### UI

화자 관리 panel에 다음을 표시한다.

- raw speaker label
- 총 발화시간
- segment 수
- 대표 segment의 재생 버튼
- 현재 canonical speaker
- clinical role

사용자는 여러 raw label을 선택하여:

- `같은 화자로 합치기`
- `별도 화자로 분리하기`
- `병합 취소`
- canonical speaker 이름 또는 role 수정

을 수행할 수 있다.

대표 audio clip은 짧은 합성/테스트 데이터에서만 제공하고 public patient page에는 노출하지 않는다.

### Data model

- raw diarization은 immutable하다.
- speaker mapping은 versioned record로 저장한다.
- 변경자, 변경시각, 이전/새 mapping을 audit event에 남긴다.
- mapping 변경은 transcript를 복사해 덮어쓰지 않고 render/query 시 적용한다.
- approved explanation을 직접 변경하지 않는다.
- 승인 후 mapping을 바꾸면 새 draft와 `REVIEW_REQUIRED`가 생성된다.

### Minimal API

현재 API와 중복되지 않게 조사한 후 필요하면 다음 의미를 추가한다.

```text
GET   /encounters/{id}/speakers
PATCH /encounters/{id}/speaker-mapping
POST  /encounters/{id}/speaker-mapping/undo
```

### Critical performance rule

speaker mapping 또는 role만 바뀐 경우:

```text
do not rerun upload
do not rerun preprocessing
do not rerun ASR
do not recompute unchanged embeddings
rerun only canonical rendering and necessary downstream LLM/validation
```

## 7. Phase 3: Automatic merge suggestions

자동 병합은 destructive action이 아니라 suggestion으로만 제공한다.

### Architecture

provider-neutral interface를 둔다.

```python
class SpeakerEmbeddingProvider(Protocol):
    def embed(self, audio_clips: list[AudioClip]) -> list[SpeakerEmbedding]: ...
```

특정 library/model은 현재 Python version, CPU/GPU, dependency size를 조사한 뒤 선택한다. 새 대형 dependency를 추가하기 전에 다음을 보고한다.

- 설치 크기
- 첫 실행 model download 크기
- CPU와 GPU latency
- license
- Korean speech 적용 가능성
- 현재 ASR provider와 중복 여부

### Clip selection

embedding 계산에서 다음 구간은 제외하거나 낮은 weight를 준다.

- 너무 짧은 segment
- 겹친 발화
- 무음 또는 매우 낮은 SNR
- 음악/비언어 소리
- clipping이 심한 구간

각 raw speaker에 대해 여러 segment embedding을 만들고 robust/weighted centroid를 구성한다. 가장 긴 한 segment만 대표로 사용하지 않는다.

### Clustering

- cosine similarity를 사용한다.
- agglomerative hierarchical clustering 또는 검증 가능한 동등 방법을 사용한다.
- threshold를 코드에 임의로 고정하지 않는다.
- 합성 fixture/golden set에서 false merge와 false split을 비교해 threshold를 정한다.
- 사용자가 예상 화자 수를 `unknown`, `2`, `3`, `4+`로 선택할 수는 있지만 강제로 맞추지 않는다.

### Cannot-link constraints

다음 raw labels는 자동으로 같은 speaker로 합치지 않는다.

- 같은 시간에 겹쳐서 발화한 labels
- 높은 confidence로 서로 다른 known-speaker reference에 매칭된 labels
- 의료진이 수동으로 `different speakers`로 고정한 labels

### Suggestion result

```json
{
  "suggested_groups": [["A", "C"], ["B"]],
  "pairwise_scores": [{"left": "A", "right": "C", "score": 0.0}],
  "warnings": [],
  "model_version": "...",
  "requires_confirmation": true
}
```

UI에는 내부 score를 절대적 확률로 표현하지 말고 `높음/중간/낮음` 추천과 근거 clip 비교를 제공한다.

## 8. Phase 4: Remove repeated work

Phase 1 benchmark에서 실제 병목으로 확인된 항목만 수정한다.

### Caching

다음 cache boundary를 검토하고 필요한 것만 구현한다.

```text
preprocess cache key:
audio_sha256 + preprocess_config_version

ASR cache key:
processed_audio_sha256 + asr_provider + model + diarization_config

speaker embedding cache key:
audio_sha256 + segment_start/end + embedding_model_version

LLM structure cache key:
canonical_transcript_hash + speaker_mapping_version + prompt_version + text_model

explanation cache key:
clinical_structure_hash + prompt_version + text_model
```

cache entry에는 생성시간과 version을 저장한다. 오류 response와 불완전한 결과는 성공 cache로 저장하지 않는다.

### Audio processing

- FFmpeg conversion을 한 pipeline run에서 한 번만 수행한다.
- denoise가 `off`이고 provider가 원본 format을 지원하면 불필요한 재인코딩을 피할 수 있는지 benchmark한다.
- 동일 파일을 메모리와 디스크에서 반복 복사하지 않는다.
- 큰 파일을 base64 JSON으로 전달하지 않고 multipart/file stream을 사용한다.

### Provider client

- backend process 안에서 thread-safe한 provider client/HTTP connection pool을 재사용한다.
- 요청마다 새 client를 만들지 않는다.
- timeout과 retry는 stage별로 명시하고 무한 재시도를 금지한다.
- retry 횟수와 retry wait를 latency metric에 기록한다.

## 9. Phase 5: Reduce LLM latency safely

먼저 `structure_llm`과 `explanation_llm` 각각의 시간을 확인한다.

### Input reduction

- 환자 설명 생성에는 전체 raw transcript 대신 검증된 clinical structure와 필요한 source spans만 전달한다.
- system prompt의 고정 부분을 앞에 두고 dynamic content를 뒤에 둔다.
- 불필요한 debug metadata와 중복 transcript를 보내지 않는다.

### Output reduction

- schema에 없는 설명문과 chain-of-thought를 요청하지 않는다.
- 짧고 구조화된 JSON만 반환하도록 한다.
- 필요 이상의 `max_output_tokens`를 사용하지 않는다.

### Fewer requests experiment

두 mode를 feature flag로 비교한다.

```dotenv
LLM_PIPELINE_MODE=separate
# separate | combined
```

- `separate`: transcript → structure JSON → patient explanation
- `combined`: 한 structured-output request에서 structure와 patient explanation을 named fields로 함께 생성

combined mode는 latency가 줄더라도 다음 eval을 모두 통과할 때만 선택 가능하다.

- unsupported diagnosis/medication/dose/numeric claim 0건
- critical omission 증가 없음
- numeric exact match 저하 없음
- clinician edit distance 악화 없음

품질이 나빠지면 separate mode를 유지한다.

### Model choice

text model은 환경변수로 설정하며 코드에 최신 model 이름을 하드코딩하지 않는다. 더 작은 model을 사용할 경우 동일 golden set으로 accuracy와 latency를 함께 비교한다.

## 10. Phase 6: Perceived latency

외부 ASR 자체가 병목이면 로컬 코드만으로 total time을 크게 줄이지 못할 수 있다. 이 경우 사용자 경험을 개선한다.

- processing endpoint는 빠르게 `202 + pipeline_run_id`를 반환한다.
- UI는 현재 stage와 경과시간을 보여준다.
- 이미 완성된 transcript segment가 있다면 의료진에게 점진적으로 보여준다.
- 실패한 stage만 재시도할 수 있게 한다.
- 새로고침 후에도 progress와 완료 결과를 복구한다.

SSE/WebSocket은 현재 polling이 실제 병목이거나 구현 복잡도 대비 이점이 있을 때만 도입한다. 단순 progress 표시만을 위해 architecture를 크게 바꾸지 않는다.

## 11. Tests and evaluation

### Speaker merge tests

- A/C를 같은 canonical speaker로 병합
- 병합 취소 후 원상복구
- overlap labels 자동 병합 금지
- manual different-speaker constraint 보존
- mapping 변경 후 ASR provider 호출 횟수 0
- 승인 후 mapping 변경 시 새 draft 생성
- raw diarization unchanged

### Automatic suggestion evaluation

최소 합성 fixture:

- 2명의 화자가 A/B/C/D 네 label로 과분할된 사례
- 비슷한 음색의 서로 다른 화자
- 동일 화자의 조용한/큰 발화
- 배경소음
- 겹친 발화
- 보호자를 포함한 3인 대화

측정:

- canonical speaker count error
- pairwise merge precision/recall
- false merge rate
- false split rate
- DER before/after가 계산 가능하면 함께 기록

의료 환경에서는 false merge를 false split보다 더 위험하게 취급한다. 확신이 낮으면 합치지 않는다.

### Performance regression tests

- warm cache에서 ASR 재호출 없음
- speaker remapping에서 preprocessing/ASR 재호출 없음
- cache config/model version 변경 시 invalidation
- provider timeout/retry 상한
- Task 01/02 approval/public access regression

## 12. Benchmark report

최적화 전후 같은 audio fixture와 같은 provider 설정으로 비교한다.

| Metric | Before | After | Change |
|---|---:|---:|---:|
| Total wall time | | | |
| Preprocess | | | |
| ASR | | | |
| Speaker processing | | | |
| Structure LLM | | | |
| Explanation LLM | | | |
| Provider calls | | | |
| Cache hits | | | |

한 번의 결과로 결론내지 말고 cold 1회와 warm 3회 이상을 구분한다.

목표는 동일 샘플 warm median total latency를 의미 있게 줄이는 것이다. 30% 이상 줄지 못하면 실패로 숨기지 말고 외부 provider-bound인지, 품질 제약 때문인지 근거와 함께 보고한다.

## 13. Acceptance criteria

- raw labels를 여러 canonical speakers로 수동 병합/분리/undo할 수 있다.
- raw diarization은 immutable하게 보존된다.
- canonical speaker와 doctor/patient/guardian role이 분리되어 있다.
- speaker mapping 변경 시 ASR을 재호출하지 않는다.
- 자동 병합은 embedding 기반 suggestion이며 확인 전 적용되지 않는다.
- overlap/manual constraints를 위반한 자동 병합이 없다.
- pipeline stage latency와 total latency가 수치로 보인다.
- 동일 audio/config의 ASR 결과를 안전하게 재사용한다.
- 같은 sample의 before/after benchmark가 제공된다.
- latency 개선 때문에 의료사실 정확도와 승인 접근제어가 악화되지 않는다.
- 일반 log에 음성, transcript 본문, API key가 없다.
- 기존 Task 01/02 test가 모두 통과한다.

## 14. Out of scope

- 음성 생체인증 또는 법적 신원확인
- 의료진 확인 없는 자동 speaker merge
- 실환자 데이터로 threshold tuning
- 근거 없이 microservice/Redis/Celery/Kubernetes 도입
- 품질평가 없는 text model 교체
- latency를 줄이기 위한 안전검증 제거

## 15. Work sequence

```text
Phase 0: current code inspection
→ Phase 1: instrumentation and baseline
→ Phase 2: manual merge and undo
→ Phase 3: automatic suggestion design/implementation
→ Phase 4: measured repeated-work removal
→ Phase 5: LLM latency experiment
→ Phase 6: UI progress improvement
→ regression tests and benchmark report
```

Phase 0–1 결과를 먼저 보고한다. 병목 데이터 없이 Phase 4–6의 최적화를 시작하지 않는다.

## 16. Done report

- 실제 병목 stage와 근거 수치
- 변경한 파일과 DB migration
- raw/canonical/role data model
- speaker merge/undo 수동 테스트 순서
- embedding model을 선택했다면 선택 근거와 resource cost
- before/after benchmark
- cache hit/miss 확인 방법
- 실행한 test와 결과
- 남은 정확도·latency·privacy 위험

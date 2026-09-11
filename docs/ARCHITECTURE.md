# ARIAD MVP Architecture

## 1. Default stack

- Web: Next.js + TypeScript
- API and AI pipeline: FastAPI + Python
- Local DB: SQLite
- Local file storage: repository 밖의 개발용 data directory
- Browser E2E: Playwright
- Python tests: pytest
- Frontend tests: Vitest

초기 MVP에는 Redis, Celery, Kafka, Kubernetes, microservice를 넣지 않는다. 오디오 처리시간 때문에 필요성이 입증되면 worker/queue를 분리한다.

## 2. Repository shape

```text
apps/
├── web/
└── api/
    ├── routes/
    ├── domain/
    ├── pipeline/
    ├── providers/
    └── repositories/
packages/
└── contracts/
prompts/
tests/
├── fixtures/
├── integration/
├── e2e/
└── evals/
```

## 3. Component responsibilities

| Component | Does | Does not do |
|---|---|---|
| Web | 입력, 상태표시, 편집, 승인, 환자 화면 | DB/ASR/LLM 직접 호출 |
| API | 인증, 권한, 상태전이, validation, orchestration | provider별 세부 구현 노출 |
| Pipeline | 단계 순서, 재시도, stage result 연결 | HTTP/UI 처리 |
| Provider adapters | ASR, diarization, LLM 호출 | 업무 상태 변경 |
| Repository | encounter/version/audit 저장 | 임상 변환 |

## 4. Minimal backend operations

```text
POST   /encounters
POST   /encounters/{id}/input
POST   /encounters/{id}/process
GET    /encounters/{id}
PATCH  /encounters/{id}/draft
POST   /encounters/{id}/approve
POST   /encounters/{id}/publish
POST   /encounters/{id}/revoke
GET    /public/explanations/{token}
```

`/public`은 승인·공개된 immutable version만 반환해야 한다.

## 5. Core pipeline functions

필요한 핵심 경계만 함수로 둔다.

```python
preprocess_audio(audio_ref, config) -> ProcessedAudio
transcribe_audio(audio, asr_provider) -> Transcript
diarize_speakers(audio, transcript, diarizer) -> SpeakerTurns
assign_speaker_roles(turns, hints) -> RoleAssignment
structure_encounter(turns, llm_provider, prompt_version) -> ClinicalStructure
generate_patient_explanation(structure, llm_provider, prompt_version) -> ExplanationDraft
validate_grounding(draft, source) -> ValidationReport
run_pipeline(encounter_id, dependencies) -> PipelineResult
```

새 helper는 이름만 다른 wrapper를 만들기 위해 추가하지 않는다. 변환 로직은 가능한 pure function으로 두고 외부 API·시간·파일·DB 접근은 경계에서만 수행한다.

## 6. Provider boundary

```python
class ASRProvider(Protocol):
    def transcribe(self, audio: ProcessedAudio) -> Transcript: ...

class DiarizationProvider(Protocol):
    def diarize(self, audio: ProcessedAudio) -> SpeakerTurns: ...

class LLMProvider(Protocol):
    def generate_json(self, prompt_id: str, payload: dict) -> dict: ...
```

로컬 기본값은 `MockASRProvider`, `MockDiarizationProvider`, `MockLLMProvider`다. 실제 provider를 연결해도 route와 domain code는 바뀌지 않아야 한다.

## 7. Data invariants

- encounter에는 현재 draft version과 선택적 approved version이 있다.
- approved version은 UPDATE하지 않는다.
- pipeline run과 각 stage run은 입력·출력 hash, prompt/provider version, 상태를 가진다.
- 일반 log는 본문 대신 ID, hash, duration, status, error code만 가진다.
- 공개 token으로 원음, 전체 전사, 내부 validation report를 조회할 수 없다.


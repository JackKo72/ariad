# Debugging and Observability

## 1. Debugging goal

“AI가 이상하다”를 허용하지 않는다. 한 실패를 특정 pipeline stage, 입력 version, provider/prompt version과 error code로 좁힐 수 있어야 한다.

## 2. Trace identifiers

한 요청에는 다음 ID를 연결한다.

```text
request_id → encounter_id → pipeline_run_id → stage_run_id
```

Frontend 오류 화면에는 개인정보가 아닌 `pipeline_run_id`를 표시해 개발자가 같은 실행을 찾게 한다.

## 3. Structured log fields

허용 필드:

- timestamp, level, environment
- request/pipeline/stage ID
- stage name, attempt, status, duration_ms
- provider/model/prompt/schema version
- input/output byte count와 hash
- error_code, retryable

금지 필드:

- 원음, 전사 본문, 환자 설명 본문
- 이름, 등록번호, 전화번호, 공개 token
- API key 또는 authorization header

합성 데이터만 쓰는 로컬 `DEBUG_ARTIFACTS=true` 모드에서는 stage artifact를 `./debug_runs/{pipeline_run_id}/`에 저장할 수 있다. 이 폴더는 gitignore하고 운영환경에서는 강제로 비활성화한다.

## 4. Error taxonomy

```text
INGEST_UNSUPPORTED_FORMAT
AUDIO_CONVERSION_FAILED
ASR_PROVIDER_TIMEOUT
ASR_EMPTY_TRANSCRIPT
DIARIZATION_NO_SPEAKER
ROLE_ASSIGNMENT_UNCERTAIN
STRUCTURE_SCHEMA_INVALID
SIMPLIFICATION_PROVIDER_FAILED
VALIDATION_UNSUPPORTED_CLAIM
VALIDATION_NUMERIC_MISMATCH
APPROVAL_STALE_VERSION
PUBLISH_NOT_APPROVED
```

각 오류는 `retryable`, 사용자에게 보일 문구, 개발자 원인, 다음 조치를 가진다.

## 5. Stage replay

전체 pipeline을 항상 다시 돌리지 않는다.

- 저장된 합성 stage input으로 한 단계만 재실행한다.
- 이전 결과와 새 결과를 JSON diff한다.
- prompt/provider 변경 시 같은 golden set을 batch replay한다.
- nondeterministic output은 raw string이 아니라 canonical JSON과 임상 필드 단위로 비교한다.

## 6. Debug playbook

### 약물 용량이 틀림

1. processed audio에 숫자가 보존됐는지 듣는다.
2. ASR segment의 숫자·단위를 확인한다.
3. speaker role이 맞는지 확인한다.
4. structured JSON의 medication 필드를 확인한다.
5. patient explanation과 source span을 비교한다.
6. 최초로 달라진 stage만 수정하고 golden test를 추가한다.

### 의사와 환자가 뒤바뀜

1. diarization의 A/B turn 경계를 확인한다.
2. overlap 구간을 확인한다.
3. role assignment confidence와 manual override를 확인한다.
4. diarization 오류와 role mapping 오류를 별개 issue로 기록한다.

### 승인 전 환자 화면에 보임

AI 문제가 아니라 access-control 결함이다. public endpoint의 approved-version 조건을 integration/E2E test로 재현하고 공개를 즉시 차단한다.

## 7. Bug report template

```md
# Bug
- pipeline_run_id:
- environment/commit:
- synthetic fixture:
- expected:
- actual:
- first failing stage:
- error code:
- provider/prompt/schema versions:
- reproduction command:
- regression test added:
```


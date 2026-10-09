# ARIAD 1단계 출력 구조 (Stage 2 Step 0 산출물)

작성일: 2026-10-09 · 기준 커밋: `6d7a31d` · 코드 변경 없음 (읽기 전용 조사)

`docs/ARIAD_stage2_design.md` Part 6-2 Step 0의 5개 질문에 답한다. Step 3(`action_directives` 추가)의 입력 문서다.

---

## 1. 진입점과 파이프라인 단계별 파일·함수

HTTP 진입점은 `POST /encounters/{id}/process` → `apps/api/app/routes/encounters.py:process_encounter` 하나다. 입력 경로는 세 가지이고, 경로에 따라 실행되는 단계가 다르다.

| 입력 경로 | 전사 출처 | enrichment 실행 | structure/explanation 실행 |
| --- | --- | --- | --- |
| 수동 텍스트 (`POST /encounters/{id}/input`) | 사용자가 붙여 넣은 `transcript_text` | ✗ (segment 없음) | ✓ `run_pipeline` |
| 오디오 업로드 (provider 모드) | ASR+diarization → `PipelineRun.segments` → 역할 확인 후 `transcript_text`로 평탄화 | ✓ | ✓ `run_pipeline` |
| 데모 샘플 (`mode == "demo"`) | fixture | ✗ | ✗ (fixture의 `*.structure.json`/`*.explanation.json`을 그대로 로드) |

단계별 파일·함수:

| 단계 | 파일 | 함수 | 입력 → 출력 |
| --- | --- | --- | --- |
| 오디오 검증·저장 | `apps/api/app/routes/audio.py`, `app/audio/validation.py`, `app/audio/storage.py` | upload 라우트 | 파일 → `AudioAsset` |
| 전처리 | `app/audio/preprocess.py` | `preprocess_audio` 계열 | 원본 → mono/16 kHz `AudioAsset(kind="processed")` |
| ASR + diarization | `app/providers/sherpa_onnx_asr.py`, `app/providers/parallel_asr.py` (`demo_asr.py`는 fixture, `unavailable_asr.py`는 미설정) | `ASRProvider.transcribe()` | audio → `list[DiarizedSegment]` (`id="seg_001"`, `speaker="A"`, `role="unknown"`, `start`, `end`, `text`) |
| ASR 후처리 (수치) | `app/pipeline/asr_normalize.py`, `app/pipeline/medication_candidates.py` | | segment text 정규화·약물명 후보 |
| 역할 확인 | `routes/encounters.py:set_speaker_roles` (`PATCH /speaker-roles`) | 의료진이 수동 확정 | `PipelineRun.roles = {"A": "doctor", ...}` |
| 전사 평탄화 | `routes/encounters.py:_derive_transcript_text` | | segments + roles → `"의사: ...\n환자: ..."` 문자열 (**segment ID는 여기서 사라진다**) |
| Clinical enrichment | `app/pipeline/enrichment.py:enrich_clinical_findings` + `enrichment_validation.py:validate_enrichment` | LLM `clinical_enrichment` | `list[DiarizedSegment]` → `ClinicalEnrichment` |
| **핵심구조화** | `app/pipeline/structure.py:structure_encounter` | LLM `structure_transcript` | `transcript_text: str` → `ClinicalStructure` |
| 환자 설명 초안 | `app/pipeline/explanation.py:generate_patient_explanation` | LLM `patient_explanation` | `ClinicalStructure.model_dump()` → `ExplanationDraft` |
| 오케스트레이션 | `app/pipeline/run.py:run_pipeline` | | structure → explanation |
| 저장 | `app/repositories/sqlite_repo.py:complete_processing` | | `encounter_versions.structure_json` / `explanation_json` / `enrichment_json` |
| 승인 시 근거 검증 | `app/pipeline/validation.py:validate_grounding` (`routes/encounters.py:approve_encounter`에서 호출) | | explanation 문장이 transcript에 그대로 있는지 |
| 환자 공개 | `app/routes/public.py:get_public_explanation` | | PUBLISHED 상태의 승인본 `ExplanationDraft`만 반환 |

LLM provider 경계: `app/providers/base.py:LLMProvider.generate_json(prompt_id, payload)`. 구현체는 `MockLLMProvider`(기본, 규칙 기반)와 `OpenAILLMProvider`(`ARIAD_MODE=provider`, structured output으로 pydantic 모델에 바인딩)다.

## 2. 핵심구조화 LLM 프롬프트 위치와 전문

- 파일: `prompts/structure_transcript.md`
- prompt_id: `structure_transcript`, 버전 상수: `app/providers/mock.py:PROMPT_VERSION_STRUCTURE = "structure_transcript@0.1.0"`
- 로딩: `app/providers/openai_llm.py:_load_prompt` → system message. user message는 `json.dumps({"transcript_text": ...})`.
- 응답 스키마: `response_format=ClinicalStructure` (OpenAI strict structured output)

전문:

````markdown
# Prompt ID: structure_transcript
Version: 0.1.0

## Role

당신은 화자가 구분된 진료 대화에서 명시적으로 언급된 임상사실을 구조화하는 보조 시스템이다. 진단하거나 치료를 제안하지 않는다.

## Input

- timestamp와 speaker role이 있는 transcript segments
- role confidence

## Rules

- 입력에 없는 사실을 추가하지 않는다.
- 부정, 불확실성, 과거력, 현재 계획을 구분한다.
- 약명, 용량, 단위, 횟수, 날짜, 수치는 원문 그대로 보존한다.
- 서로 모순되면 하나를 선택하지 말고 conflict로 표시한다.
- 불명확하면 추측하지 말고 `needs_confirmation=true`로 둔다.
- 각 중요 사실에 근거 segment ID를 연결한다.

## Output

JSON schema가 요구하는 필드만 반환한다.

```json
{
  "problems": [{"text": "", "certainty": "stated|uncertain", "source_segment_ids": []}],
  "tests": [{"name": "", "reason": "", "status": "planned|completed|unknown", "source_segment_ids": []}],
  "medications": [{"name": "", "dose": "", "route": "", "frequency": "", "action": "start|continue|stop|unknown", "source_segment_ids": [], "needs_confirmation": false}],
  "plan": [{"text": "", "source_segment_ids": []}],
  "warnings": [{"text": "", "source_segment_ids": []}],
  "follow_up": [{"text": "", "source_segment_ids": []}],
  "questions_or_conflicts": []
}
```
````

> ⚠ 프롬프트의 `## Input`은 "timestamp와 speaker role이 있는 transcript segments"라고 적혀 있지만, 실제 payload는 `{"transcript_text": "의사: ...\n환자: ..."}` 평탄화 문자열이다. timestamp도 segment ID도 전달되지 않는다 (§4 참조).

참고로 enrichment 프롬프트(`prompts/clinical_enrichment.md`, `clinical_enrichment@0.1.0`)는 segment 리스트(`id`, `speaker`, `role`, `start`, `end`, `text`)를 실제로 받는다.

## 3. 최종 출력 JSON의 실제 스키마

### 3-1. `ClinicalStructure` (핵심구조화 LLM 출력)

정의: `apps/api/app/domain/models.py:ClinicalStructure` / 계약: `packages/contracts/schema/clinical_structure.schema.json` (최상위 `additionalProperties: false`) / 프론트: `apps/web/lib/types.ts:ClinicalStructure`

| 필드 | 타입 | 항목 필드 |
| --- | --- | --- |
| `problems` | `Problem[]` | `text: str`, `certainty: "stated"\|"uncertain"`, `source_segment_ids: str[]` |
| `tests` | `TestOrder[]` | `name: str`, `reason: str`, `status: "planned"\|"completed"\|"unknown"`, `source_segment_ids: str[]` |
| `medications` | `Medication[]` | `name`, `dose`, `route`, `frequency: str`, `action: "start"\|"continue"\|"stop"\|"unknown"`, `source_segment_ids: str[]`, `needs_confirmation: bool` |
| `plan` | `PlanItem[]` | `text: str`, `source_segment_ids: str[]` |
| `warnings` | `PlanItem[]` | 〃 |
| `follow_up` | `PlanItem[]` | 〃 |
| `questions_or_conflicts` | `str[]` | |

ID·방문 메타데이터·요약 필드는 없다. 이 객체는 아래 `EncounterVersion` 안에 담겨 저장·반환된다.

예시 (`tests/fixtures/audio/sample_consultation.structure.json`, 합성 데이터, 일부 생략):

```json
{
  "problems": [{"text": "혈압이 145/92로 높게 측정됨", "certainty": "stated", "source_segment_ids": ["seg_001"]}],
  "tests": [],
  "medications": [
    {"name": "리시노프릴", "dose": "5mg", "route": "경구", "frequency": "하루 한 번 아침",
     "action": "start", "source_segment_ids": ["seg_003"], "needs_confirmation": false}
  ],
  "plan": [{"text": "2주 후 10월 첫째 주 재방문하여 혈압 확인", "source_segment_ids": ["seg_007"]}],
  "warnings": [{"text": "심한 두통, 가슴 통증, 호흡곤란 발생 시 즉시 응급실 방문", "source_segment_ids": ["seg_009"]}],
  "follow_up": [{"text": "10월 첫째 주 혈압 재확인", "source_segment_ids": ["seg_007"]}],
  "questions_or_conflicts": []
}
```

### 3-2. 감싸는 객체 `EncounterVersion` (API `GET /encounters/{id}` 응답의 `draft_version`/`approved_version`)

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `id` | str | `uuid4().hex` (`app/ids.py:new_id`) |
| `encounter_id` | str | uuid4 hex. 설계 문서의 `visit_id`에 해당 |
| `version_number` | int | 승인 후 수정 시 새 draft version 생성 |
| `status` | `"draft"\|"approved"` | 승인본은 불변 |
| `transcript_text` | str | 평탄화 전사 |
| `structure` | `ClinicalStructure` | |
| `explanation` | `ExplanationDraft` | 환자 공개 대상은 이것뿐 |
| `enrichment` | `ClinicalEnrichment \| None` | 오디오 경로에서만 채워짐 |
| `prompt_version_structure` / `_explanation` / `_enrichment` | str \| None | |
| `created_at`, `approved_at` | str | |

### 3-3. 관련 엔티티 `ClinicalEnrichment` (오디오 경로 전용)

`medications`, `symptoms`, `exam`, `diagnoses`, `follow_up_questions`, `plan`, `validator_violations`. 모든 finding은 `id`, `raw_text`(원문 그대로), `needs_review`, `source_spans: SourceSpan[]`를 가진다. `SourceSpan = {segment_id, quote, speaker(A/B/C), role(doctor/patient/guardian/unknown), start, end}`. `plan[]`의 `PlanFinding`은 `kind: "directive"|"discussion"`, `polarity: "affirmed"|"negated"|"question"|"uncertain"`를 가진다 — 설계의 `action_directives`와 가장 가까운 기존 구조다. `validate_enrichment`가 quote가 실제 segment text의 부분 문자열인지 기계적으로 검사한다.

## 4. 발화 단위 ID(utterance id)

| 경로 | ID 존재 | 형식 | 부여 위치 |
| --- | --- | --- | --- |
| 오디오 (sherpa-onnx) | ✓ | `seg_001`… | `app/providers/sherpa_onnx_asr.py:532` |
| 오디오 (parallel ASR) | ✓ | `seg_001`… | `app/providers/parallel_asr.py:391` |
| 데모 fixture | ✓ | `seg_001`… | `tests/fixtures/audio/*.transcript.json` → `demo_asr.py` |
| 수동 텍스트 | ✗ | — | 없음. 저장되는 건 `transcript_text` 문자열뿐 |
| Mock structure 출력 | (가짜) | `seg-1`… (하이픈) | `app/providers/mock.py:_segment_transcript`가 줄 번호로 즉석 생성 |

ID는 `PipelineRun.segments_json`(`pipeline_runs` 테이블)에 저장되고 `EncounterVersion`에는 직접 연결되지 않는다.

**핵심 문제**: 핵심구조화 LLM은 `_derive_transcript_text`가 만든 평탄화 문자열만 받으므로 **segment ID를 볼 수 없다**. 따라서 provider 모드에서 `ClinicalStructure.*.source_segment_ids`는 LLM이 추측한 값이고 검증도 되지 않는다. 같은 대화에서도 mock은 `seg-1`, ASR은 `seg_001`을 쓴다.

부여할 수 있는 위치 (Step 3에서 결정 필요):

- **A.** `_derive_transcript_text`가 각 줄에 ID를 앞에 붙임 (`[seg_003] 의사: ...`) → structure LLM이 ID를 볼 수 있음. 수동 텍스트 경로는 `submit_input` 시점에 줄 단위 `seg_001` 부여 규칙을 정해 mock과 형식을 맞춤.
- **B.** `action_directives`를 `ClinicalStructure` 대신 segment를 이미 받는 `ClinicalEnrichment` 쪽에 추가 → ID는 그대로 근거 있음, `validate_enrichment`의 quote 검증 재사용 가능. 단 수동 텍스트·데모 경로에서는 enrichment가 `None`.
- **C.** structure payload에 `segments`를 함께 넘김 (`{"transcript_text", "segments"}`) — 프롬프트 Input 설명과도 일치하게 됨.

## 5. `action_directives` 추가 시 영향받는 소비 코드

`ClinicalStructure`에 필드를 추가한다고 가정한 목록이다 (B안이면 괄호 안 `ClinicalEnrichment` 쪽 대응 파일).

| # | 파일 | 영향 | 깨지는가 |
| --- | --- | --- | --- |
| 1 | `apps/api/app/domain/models.py` | 새 모델 + 필드 추가 (`default_factory=list`) | — |
| 2 | `packages/contracts/schema/clinical_structure.schema.json` | 최상위 `additionalProperties: false` | **✓ 스키마 갱신 안 하면 계약 위반** |
| 3 | `apps/api/tests/test_contract_schema.py` | mock 출력을 위 스키마로 검증 | **✓ (2)와 함께 수정 필요** |
| 4 | `app/providers/openai_llm.py` + `tests/test_openai_llm_provider.py::test_clinical_structure_and_explanation_draft_are_openai_strict_schema_compatible` | strict mode는 중첩 객체마다 명시 모델 필요, `dict[str, Any]` 금지 | 자유형 dict로 정의하면 ✓ |
| 5 | `app/providers/mock.py:_structure_transcript`, `PROMPT_VERSION_STRUCTURE` | mock 출력에 필드 추가, 프롬프트 버전 올림 | 기본값 있으면 ✗ |
| 6 | `prompts/structure_transcript.md` | 추출 지시 + Output 예시 추가 | — |
| 7 | `app/pipeline/structure.py:structure_encounter` | `model_validate` | ✗ |
| 8 | `app/pipeline/explanation.py` | **`structure.model_dump()` 전체를 환자 설명 LLM에 넘김** → 환자 장벽 발화(`barrier_mentions`)·동의 정도까지 환자 설명 초안 입력에 섞임 | 깨지진 않지만 **의미상 영향** — 제외 여부 결정 필요 |
| 9 | `app/repositories/sqlite_repo.py` (`structure_json`), `app/db.py` | JSON 컬럼, 마이그레이션 불필요. 기존 행은 기본값으로 로드 | ✗ |
| 10 | `app/routes/encounters.py` `UpdateDraftRequest` (`PATCH /draft`) | 요청 바디가 `ClinicalStructure` 전체 | 구 클라이언트가 필드를 빼면 **빈 리스트로 덮어씀** (데이터 유실 위험) |
| 11 | `apps/web/lib/types.ts`, `lib/textFields.ts:buildStructureFromText`, `lib/textFields.test.ts`, `app/encounters/[id]/EncounterDetailClient.tsx` | `...original` 스프레드라 필드는 보존됨. 타입에는 없음 | ✗ (TS 타입 추가 권장) |
| 12 | `app/providers/demo_asr.py` + `tests/fixtures/audio/sample_consultation.structure.json` | fixture에 필드 없음 → 기본값 | ✗ |
| 13 | `app/pipeline/validation.py`, `app/routes/public.py` | explanation만 다룸 | ✗ (환자 endpoint로 새지 않음) |
| 14 | `scripts/benchmark_audio.py`, `scripts/test_provider_audio.py` | `structure_encounter` 호출만 | ✗ |
| 15 | `apps/api/tests/test_mock_provider.py`, `tests/integration/*` | 구조 비교 테스트가 있으면 갱신 | 확인 필요 |
| (B안) | `ClinicalEnrichment`, `prompts/clinical_enrichment.md`, `enrichment_validation.py`, `PROMPT_VERSION_ENRICHMENT`, mock `_clinical_enrichment` | enrichment 쪽 동일 작업 | |

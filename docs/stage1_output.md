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

---

## 6. 결정 기록 (2026-10-09)

- **발화 ID 부여: C안 채택.** 핵심구조화 단계(`structure_encounter`)에 평탄화 문자열과 함께 `segments`(id·role·text)를 넘기고, `action_directives`는 `ClinicalStructure`에 추가한다. 구현은 Step 3에서 한다 (Step 1·2에서는 코드 변경 없음).
- C안에서 Step 3이 함께 풀어야 할 것:
  - 수동 텍스트 경로: `transcript_text`를 줄 단위로 나눠 `seg_001` 형식 ID를 부여하는 순수 함수 1개를 두고, mock(`seg-1`)도 같은 형식으로 맞춘다.
  - LLM이 낸 `utterance_ids`가 실제 segment ID 집합에 있는지, `raw_text`가 해당 segment text의 부분 문자열인지 기계 검증한다 (`enrichment_validation.py`와 같은 방식). 실패하면 재시도 1회 후 `needs_review`.

## 7. 설계(Part 5-2)와 실제의 어긋남 7–11 상세

### 7번. 핵심구조화 LLM은 발화 ID를 볼 수 없다

**지금 실제로 일어나는 일** (오디오 경로, provider 모드):

```text
① ASR 결과 (pipeline_runs.segments_json)
   seg_003 | speaker=A | role=doctor  | "국물은 이제 드시지 마시고요"
   seg_004 | speaker=B | role=patient | "그게 제일 어렵네요"

② _derive_transcript_text()  ← 여기서 ID가 버려진다
   "의사: 국물은 이제 드시지 마시고요\n환자: 그게 제일 어렵네요"

③ structure LLM 입력 = {"transcript_text": "<②의 문자열>"}
   → LLM 출력: {"plan": [{"text": "...", "source_segment_ids": ["???"]}]}
```

LLM은 `seg_003`이라는 문자열을 한 번도 보지 못했는데 `source_segment_ids`를 채우라는 지시를 받는다. 그러면 `seg-1`, `U-1`, `1`처럼 그럴듯한 값을 **지어낼** 수밖에 없고, 지금은 이를 검증하는 코드도 없다.

**왜 문제인가**: 설계의 핵심 가치는 "의사가 무엇을 말했고(원 발화) → 환자가 무엇을 했는가"를 이어 주는 것(Part 5 추적성)이다. `utterance_ids`가 가짜면 리포트의 "원 발화" 칸이 엉뚱한 문장을 가리키게 되고, 의료진이 근거를 확인할 수 없다. 이는 CLAUDE.md의 "입력에 없는 … 생성하지 않는다"에도 걸린다.

**C안이 바꾸는 것**: ③의 입력을 `{"transcript_text": ..., "segments": [{"id": "seg_003", "role": "doctor", "text": "..."}, ...]}`로 넓힌다. LLM은 실제 ID를 복사만 하면 되고, 코드는 "출력 ID ⊂ 입력 ID"를 검사할 수 있다.

### 8번. "새 필드는 무시해도 안 깨진다"는 가정이 이 리포에서는 틀리다

`packages/contracts/schema/clinical_structure.schema.json` 최상위가 이렇게 되어 있다.

```json
{ "type": "object", "required": [...7개...], "additionalProperties": false, ... }
```

`additionalProperties: false`는 "**선언되지 않은 키가 하나라도 있으면 실패**"라는 뜻이다. 그래서 mock이 `action_directives`를 출력하는 순간 `apps/api/tests/test_contract_schema.py::test_structure_transcript_output_matches_schema`가 실패한다.

이건 버그가 아니라 의도된 안전장치다(LLM이 엉뚱한 필드를 끼워 넣는 걸 막음). 따라서 Step 3에서는 **필드 추가와 같은 커밋에서** 스키마 JSON에 `action_directives` 정의를 함께 넣어야 한다. 기존 7개 필드는 건드리지 않으므로 stage 2 규칙("필드 추가만 허용")은 지켜진다.

같은 맥락으로 OpenAI strict 모드도 걸린다. `action_directives: list[dict]`처럼 느슨하게 정의하면 OpenAI가 400 오류로 거부한다(`test_..._openai_strict_schema_compatible`가 이걸 잡는 회귀 테스트). `ActionDirective`, `PatientResponse`, `BarrierMention` 같은 중첩 객체마다 명시적인 pydantic 모델이 필요하다.

### 9번. 환자 설명 LLM이 `action_directives`까지 받게 된다

`app/pipeline/explanation.py`:

```python
llm_provider.generate_json("patient_explanation", {"structure": structure.model_dump()})
```

`model_dump()`는 **모든 필드**를 넘긴다. `action_directives`를 추가하면 환자 설명 초안을 쓰는 LLM 입력에 다음이 섞인다.

- `patient_response.text`: "그게 제일 어렵네요"
- `patient_response.agreement`: `"hesitant"`
- `barrier_mentions`: "혼자 살아서 라면을 자주 먹어요"

**위험**: 환자용 설명에 "환자분은 국물 줄이기를 망설이셨습니다", "혼자 사셔서…" 같은 문장이 들어갈 수 있다. 의료진 승인 단계에서 걸러지긴 하지만, 2단계 내부 데이터(동의 정도·장벽)가 환자 문서로 새는 경로가 생긴다. 반대로 의사의 지시 문장(`raw_text`)은 환자 설명에 들어가도 되는 내용이다.

**Step 3에서 정할 것**: explanation payload에서 `action_directives`를 빼거나(`model_dump(exclude={"action_directives"})`), 지시 문장만 남기고 환자 반응·장벽은 뺀다. 기본 권장은 **전부 제외**다. 1단계 환자 설명은 지금처럼 기존 7개 필드만으로 만들고, 행동 계획은 2단계 Action Plan(의료진 승인 후 별도 발송)으로 환자에게 간다.

### 10번. 같은 개념을 다른 이름으로 부른다

| 개념 | 설계 (5-2) | 리포에 이미 있는 것 | 차이 |
| --- | --- | --- | --- |
| 환자가 지시에 동의한 정도 | `agreement`: agreed / hesitant / refused / unclear | 없음 | 새 개념이라 그대로 추가해도 됨 |
| 진술이 긍정인지 부정인지 | 없음 | `polarity`: affirmed / negated / question / uncertain (enrichment) | **다른 개념**. "드시지 마세요"는 polarity=negated 지시지만 agreement와는 무관 |
| 사람이 봐야 함 | 없음 | structure는 `needs_confirmation`, enrichment는 `needs_review` | 리포 안에서도 이름이 둘 |

**왜 중요한가**:

- 설계의 `action_directives`에는 "확실하지 않음" 플래그가 없다. 하지만 CLAUDE.md는 "불확실한 화자 역할이나 임상 사실은 검토 필요 상태로 보낸다"를 요구하고, stage 2 규칙도 "LLM 출력 검증 실패 시 needs_review로 저장"이라고 한다. 따라서 `ActionDirective`에 **`needs_review: bool`을 추가**해야 한다 (enrichment와 같은 이름, stage 2 규칙과 같은 이름).
- `agreement="unclear"`와 `needs_review=true`는 별개다. 앞의 것은 "환자가 애매하게 대답함"(임상 정보), 뒤의 것은 "모델이 추출을 확신하지 못함"(품질 정보)이다.

### 11번. enrichment의 `plan[]`이 이미 비슷한 일을 한다

오디오 경로에서는 `ClinicalEnrichment.plan[]`이 이미 이렇게 생겼다.

```json
{ "id": "plan-seg_003", "raw_text": "국물은 이제 드시지 마시고요", "kind": "directive",
  "polarity": "affirmed", "needs_review": true,
  "source_spans": [{"segment_id": "seg_003", "quote": "...", "speaker": "A", "role": "doctor"}] }
```

설계의 `action_directive`와 비교하면 다음과 같다.

| | enrichment `PlanFinding` | 설계 `action_directive` |
| --- | --- | --- |
| 원문 그대로 | `raw_text` ✓ | `raw_text` ✓ |
| 발화 ID | `source_spans[].segment_id` ✓ (검증됨) | `source_span.utterance_ids` |
| 지시인지 단순 논의인지 | `kind` ✓ | 없음 |
| 생활습관 영역·목표값 | ✗ | `domain_hint`, `target_hint` |
| 환자 반응·장벽 | ✗ | `patient_response`, `barrier_mentions` |
| 수동 텍스트 경로 | ✗ (오디오만) | ✓ (필요) |

**C안을 고른 이유와 연결**: B안(enrichment에 붙이기)은 ID 검증을 공짜로 얻지만 수동 텍스트 경로에서 동작하지 않는다. C안은 structure 쪽에 붙이되, **`PlanFinding`의 좋은 점(원문 그대로 저장, quote 부분 문자열 검증, `needs_review`)을 그대로 빌려 온다**. 두 구조가 공존하므로 Step 3에서는 다음을 지킨다.

- `ActionDirective`의 발화 참조 필드는 enrichment와 같은 이름(`segment_id`)·형식(`seg_001`)을 쓴다.
- 설계의 `source_span.speaker: "doctor"`는 `role`로 저장한다. 리포에서 `speaker`는 A/B/C 라벨이라 이름을 그대로 쓰면 6번 문제가 재발한다.

## 8. 7–11 해결 현황 (Step 2 완료 시점, 2026-10-10)

Step 2는 **모델 정의**(`apps/api/app/domain/stage2.py`)만 만든다. 1단계 코드에 연결하는 작업은 Step 3이다.

| # | Step 2에서 해결 (모델) | Step 3에서 해결 (1단계 코드 연결) |
| --- | --- | --- |
| 7 | `ActionDirective.source_spans`가 기존 `SourceSpan`을 재사용 → `segment_id`(`seg_003`)·`speaker`(A/B)·`role`(`doctor`)·`quote` 태그를 모두 유지 | structure payload에 `segments` 추가, 수동 텍스트 경로 `seg_001` 부여, mock `seg-1`→`seg_001`, "출력 ID ⊂ 입력 ID" 검증 |
| 8 | 중첩 객체 전부 명시 모델. strict 호환 테스트를 강화(SDK가 자유형 dict를 오류 없이 빈 객체로 바꾸는 문제까지 검사) | `clinical_structure.schema.json`에 `action_directives` 정의 추가, `ClinicalStructure`에 필드 연결 |
| 9 | — (모델과 무관) | `explanation.py`에서 `model_dump(exclude={"action_directives"})` |
| 10 | `Agreement` Enum(4값)과 `needs_review: bool = True`를 별도 필드로 둠 | grounding 검증 통과 시에만 `needs_review=false` |
| 11 | 발화 참조 이름·형식을 enrichment와 통일(`source_spans[].segment_id`, `role`) | — |

설계와 달라진 이름: `visit_id` → `ActionPlan.encounter_id`, `source_span.utterance_ids` → `source_spans[].segment_id`, `source_span.speaker:"doctor"` → `source_spans[].role`, `patient_response.utterance_id` → `patient_response.source_spans`.

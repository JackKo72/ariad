# ARIAD AI Pipeline

## 1. Principle

전체 처리를 하나의 거대한 LLM 호출로 만들지 않는다. 각 단계는 typed input/output을 가지며 독립적으로 저장·검사·재실행할 수 있어야 한다.

## 2. Stages

| Stage | 최소 구현 | 산출물 | 주 실패 원인 |
|---|---|---|---|
| Ingest | 형식·길이·동의 확인, hash 생성 | `AudioInput` | 잘못된 형식, 동의 없음 |
| Audio preprocess | mono/16 kHz PCM 변환, loudness 정규화, 선택적 light denoise | `ProcessedAudio` | codec, 과도한 제거 |
| ASR | timestamp가 있는 한국어 전사 | `TranscriptSegment[]` | 의학용어·수치·고유명사 오류 |
| Diarization | Speaker A/B/C 구간 분리 | `SpeakerTurn[]` | 겹침, 짧은 발화, 잡음 |
| Role assignment | speaker를 doctor/patient/guardian/unknown으로 매핑 | `RoleAssignment` | role 확신 부족 |
| Structure | 원문에 있는 임상사실만 JSON으로 추출 | `ClinicalStructure` | 누락, 잘못된 slot |
| Simplification | 구조화 사실을 쉬운 한국어로 변환 | `ExplanationDraft` | 환각, 의미 약화, 위험 누락 |
| Validation | schema, 수치/약물, 근거, 금지표현 검사 | `ValidationReport` | unsupported claim |
| Review/publish | 사람이 수정·승인 후 immutable version 공개 | `ApprovedExplanation` | 권한·version 오류 |

## 3. Speaker handling

`diarization`은 누가 말했는지를 A/B/C로 군집화하는 일이고, `role assignment`는 그 군집을 의사/환자/보호자로 해석하는 일이다. MVP에서는 생체 음성 식별을 하지 않는다.

- 자동 role assignment에는 confidence와 근거 규칙을 남긴다.
- confidence가 기준 미만이거나 보호자가 추가되면 의료진이 직접 역할을 확인한다.
- 겹친 발화는 한 화자에게 임의 할당하지 말고 `overlap=true`로 표시한다.

## 4. Noise reduction

- 원본을 덮어쓰지 않고 processed artifact를 별도로 만든다.
- 기본은 resampling, channel normalization, loudness normalization이다.
- denoise는 `off|light` feature flag로 시작한다.
- denoise 전후 합성 평가세트의 Korean CER를 비교해 개선되지 않으면 사용하지 않는다.
- 음성을 깨끗하게 보이게 하는 것보다 약명·용량·수치 보존을 우선한다.

## 5. Easy-language generation

쉬운 언어 변환은 원문 전체를 바로 요약하지 않는다.

```text
speaker-attributed transcript
→ clinical fact JSON
→ patient explanation JSON
→ source-grounding validation
→ clinician review
```

- 진단, 검사, 약물, 용량, 일정, warning sign은 별도 필드로 유지한다.
- 수치와 고유명사는 paraphrase 대상이 아니다.
- 정보가 없으면 빈 값 또는 `needs_confirmation`을 사용한다.
- “괜찮다”, “안전하다”, “반드시 좋아진다” 같은 근거 없는 안심 표현을 금지한다.

## 6. Versioning

각 pipeline run에 다음을 고정한다.

- source audio/transcript hash
- preprocessing config version
- ASR/diarization provider와 model version
- structure/simplification prompt ID와 version
- JSON schema version
- application commit SHA

이 정보가 있어야 동일 입력을 재현하고 변경 전후 품질을 비교할 수 있다.


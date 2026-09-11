# ARIAD MVP Product Specification

## 1. Problem

진료 중 설명이 제공되어도 환자와 보호자가 진단, 검사 이유, 치료계획, 주의사항과 다음 행동을 정확히 이해했다고 보장할 수 없다. ARIAD는 면담 내용을 근거로 의료진 검토용 초안과 환자용 쉬운 설명을 만든다.

## 2. MVP user-facing function budget

MVP의 사용자 기능은 아래 다섯 개로 제한한다.

1. 의료진이 새 면담을 만들고 동의를 확인한다.
2. 음성파일 또는 합성 전사문을 입력한다.
3. 처리 상태와 단계별 오류를 확인한다.
4. 전사·구조화 결과·환자 설명을 수정하고 승인한다.
5. 환자는 승인된 설명만 모바일 페이지에서 본다.

## 3. Non-goals

- 자동 진단 또는 치료 추천
- 자동 처방과 EMR write-back
- 의료진 검토 없는 환자 공개
- 실시간 진료 녹음 최적화
- 생체 음성인식으로 실제 신원 확인
- 문자·카카오톡 발송, 결제, 다기관 관리
- 범용 환자행동·복약관리 플랫폼

## 4. Roles

### Clinician

면담 생성, 입력 제출, 전사 교정, 화자 역할 확인, 설명 수정, 승인·취소를 수행한다.

### Patient or guardian

승인되고 아직 폐기되지 않은 환자 설명만 읽는다.

### System

파이프라인 실행, 입력/출력 schema 검증, 단계별 상태·버전·감사 사건 기록을 수행한다. 임상 판단 주체가 아니다.

## 5. Main flow

```text
Create encounter
→ confirm consent
→ paste transcript or upload audio
→ process stages
→ clinician review
→ approve immutable version
→ publish patient view
```

## 6. States

`DRAFT → SUBMITTED → PROCESSING → REVIEW_REQUIRED → APPROVED → PUBLISHED`

예외 상태는 `PROCESSING_FAILED`, 공개 철회는 `REVOKED`다. 승인 후 본문 수정은 기존 승인본을 바꾸지 않고 새 `REVIEW_REQUIRED` draft를 만든다.

## 7. First vertical slice

실제 ASR보다 먼저 합성 전사문으로 전체 흐름을 완성한다. 입력, mock 구조화, mock 환자 설명, 수정, 승인, 환자 공개와 접근제어가 브라우저에서 이어져야 한다. 그 다음 audio pipeline을 같은 인터페이스 뒤에 연결한다.

## 8. MVP success measures

- 환자 공개 전에 반드시 의료진 승인이 있었던 비율: 100%
- 합성 평가세트에서 근거 없는 중요 임상사실: 0건
- 약명·용량·검사수치·날짜의 원문 일치 여부를 자동 평가 가능
- 의료진의 평균 검토시간과 수정량을 기록 가능
- 실패를 `audio`, `ASR`, `diarization`, `structure`, `simplification`, `validation`, `publish` 중 한 단계로 분류 가능


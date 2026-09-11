# Task 01: Transcript-to-approved-page vertical slice

## Outcome

의료진이 합성 전사문을 제출하고 mock 환자 설명을 수정·승인하면 환자용 모바일 페이지에서 승인본만 볼 수 있다.

## Read first

- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`
- `docs/TESTING_AND_EVALS.md`

## In scope

- Next.js web와 FastAPI API 최소 scaffold
- SQLite local persistence
- 합성 전사문 입력
- deterministic mock structure/explanation
- 처리, 검토, 승인, 공개 상태
- 승인본 immutable version
- public token endpoint
- loading/empty/error UI
- 실행/테스트 명령과 README

## Out of scope

- 음성 업로드·ASR·화자분리·실제 LLM
- 실제 로그인, EMR, 알림, 운영 배포
- UI component library와 복잡한 디자인 시스템

## Acceptance criteria

- 새 합성 면담을 생성하고 처리할 수 있다.
- mock output을 수정하면 draft version이 저장된다.
- 승인 전 public endpoint는 내용을 반환하지 않는다.
- 승인 시 immutable approved version과 감사 사건이 생성된다.
- 승인 후 수정하면 새 draft가 생기고 기존 승인본은 변하지 않는다.
- 공개 후 모바일 페이지는 승인 version만 표시한다.
- 페이지 새로고침 후 상태가 유지된다.
- unit, API integration, Playwright E2E, lint/typecheck가 통과한다.

## Work instruction

먼저 계획만 제시한다. 승인 후 가장 작은 구현을 만들고 범위를 넓히지 않는다. 실제 환자 정보와 외부 AI API를 사용하지 않는다.


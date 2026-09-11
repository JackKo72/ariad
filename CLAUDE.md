# ARIAD Coding Instructions

## Mission

ARIAD는 진료 대화를 전사·구조화하고 환자가 이해하기 쉬운 설명 초안을 만드는 의료진 보조 도구다. 모든 환자용 결과는 의료진 승인 후에만 공개한다.

## Read before editing

- 제품 기능 변경: `docs/PRODUCT.md`
- 컴포넌트/API 변경: `docs/ARCHITECTURE.md`
- AI 단계 변경: `docs/AI_PIPELINE.md`
- 로그/오류 처리 변경: `docs/DEBUGGING.md`
- 테스트 기준 변경: `docs/TESTING_AND_EVALS.md`
- 이번 범위: 사용자가 지정한 `tasks/*.md`

## Minimal implementation rules

- 한 번에 task 하나만 구현한다. task 밖 기능은 TODO로도 몰래 추가하지 않는다.
- 새 abstraction은 두 곳 이상에서 실제로 반복되거나 provider 교체 경계일 때만 만든다.
- 함수 하나는 한 단계만 수행하고, 입력과 출력 타입을 명시한다.
- 숨은 전역 상태를 두지 않는다. 시간·provider·저장소 의존성은 주입한다.
- 먼저 동작하는 가장 작은 vertical slice를 만든다.
- worker, Redis, microservice, event bus는 요구가 생기기 전에는 추가하지 않는다.
- Frontend는 DB, ASR, LLM provider를 직접 호출하지 않는다.
- ASR/LLM은 adapter 뒤에 둔다. 기본 로컬 모드는 mock이다.

## Medical and privacy rules

- 테스트에는 합성 데이터만 사용한다.
- 원음, 전사, 환자 설명 본문을 일반 application log에 남기지 않는다.
- 입력에 없는 진단·약물·용량·수치·날짜를 생성하지 않는다.
- 불확실한 화자 역할이나 임상 사실은 검토 필요 상태로 보낸다.
- 승인 전 결과는 환자 endpoint에서 반환하지 않는다.
- 승인본은 불변이며 수정 시 새 draft version을 만든다.

## Required workflow

코드 수정 전 현재 코드, 관련 docs, 지정 task를 읽고 짧은 계획을 제시한다. 구현 후 관련 unit, integration, E2E/eval을 실행한다. 실패한 테스트를 숨기거나 우회하지 않는다.

최종 보고에는 다음을 포함한다.

- 구현한 것과 의도적으로 구현하지 않은 것
- 변경 파일
- 실행한 테스트와 결과
- 직접 재현하는 명령
- 개인정보·의료안전·품질상 남은 위험


# ARIAD

진료 대화를 전사·구조화하고 환자가 이해하기 쉬운 설명 초안을 만드는 의료진 보조 도구.
모든 환자용 결과는 의료진 승인 후에만 공개된다.

현재 구현 범위는 `tasks/01_VERTICAL_SLICE.md` (합성 전사문 → mock 구조화/설명 → 검토·승인 →
환자 공개). 실제 음성 업로드/ASR/화자분리/실제 LLM은 아직 없다 (`tasks/02_AUDIO_PIPELINE.md`
이후).

## Stack

- Web: Next.js (App Router) + TypeScript, `apps/web`
- API + pipeline: FastAPI + Python, `apps/api`
- DB: SQLite (로컬 파일)
- 기본 provider: `MockLLMProvider` (외부 API 호출 없음, 결정론적 출력)

## 처음 실행하기

```bash
make doctor   # 필수 도구 확인
make setup    # apps/api venv + apps/web node_modules + 루트(Playwright) 설치
make dev      # API :8000 + Web :3000 동시 실행 (Ctrl+C로 종료)
```

`make dev` 실행 후 브라우저에서 `http://localhost:3000` 접속:

1. 동의 확인 체크 후 새 면담 생성
2. 합성 전사문(텍스트) 입력 → 제출
3. 처리 시작 → mock 구조화/환자 설명 확인
4. 필요시 내용 수정 → 승인
5. 공개하기 → 표시된 `/p/{token}` 링크가 환자용 페이지

## 테스트

```bash
make test    # pytest (unit/contract/integration, apps/api + tests/integration) + vitest (apps/web)
make e2e     # Playwright 브라우저 E2E (API+Web 자동 기동)
make eval    # 합성 golden set에 대해 mock pipeline grounding 검사
make lint    # ruff (api) + eslint + tsc --noEmit (web)
```

## 디렉터리 구조

```text
apps/
├── web/                 # Next.js 클라이언트. DB/LLM을 직접 호출하지 않고 apps/api만 호출한다.
└── api/
    ├── app/
    │   ├── domain/       # 상태 모델, 상태전이 규칙, 에러 코드
    │   ├── pipeline/      # structure_encounter / generate_patient_explanation / validate_grounding
    │   ├── providers/     # LLMProvider 경계 + MockLLMProvider (기본, ARIAD_MODE=mock)
    │   ├── repositories/  # SQLite 저장 (encounter/version/audit)
    │   └── routes/        # /encounters/*, /public/explanations/{token}
    └── tests/             # unit + contract (mock 출력 vs JSON schema)
packages/contracts/schema/ # ClinicalStructure / ExplanationDraft JSON schema
tests/
├── fixtures/    # 합성 전사문 (초기 3건)
├── integration/ # API+SQLite, 접근제어, 승인 불변성
├── e2e/         # Playwright
└── evals/       # make eval 스크립트
```

## 환경변수

`.env.example` 참고. 기본값은 모두 로컬 mock 모드로 동작하도록 되어 있다.

## 알려진 제한 (task 01 범위 밖)

- 음성 업로드, 실제 ASR/화자분리, 실제 LLM 연동 없음 (mock만 존재)
- 실 로그인 없음 (단일 고정 clinician으로 간주, API 인증 없음)
- 승인된 면담이 `PUBLISHED` 상태일 때는 수정이 불가하다 (먼저 `공개 취소` 후 편집).
  `APPROVED`(공개 전) 상태에서의 편집만 지원.
- CORS는 로컬 개발 origin(`http://localhost:3000`)만 허용하도록 고정되어 있다.

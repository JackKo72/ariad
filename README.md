# ARIAD

진료 대화를 전사·구조화하고 환자가 이해하기 쉬운 설명 초안을 만드는 의료진 보조 도구.
모든 환자용 결과는 의료진 승인 후에만 공개된다.

구현 범위:

- `tasks/01_VERTICAL_SLICE.md`: 합성 전사문 → mock 구조화/설명 → 검토·승인 → 환자 공개 (완료)
- `tasks/02_AUDIO_PIPELINE.md` Phase A: 로컬 음성파일 업로드·검증(ffprobe)·원본 재생 (완료)
- `tasks/02_AUDIO_PIPELINE.md` Phase B: FFmpeg 표준화(mono/16kHz/16bit) + 원본/가벼운 소음처리 비교 재생 (완료)
- `tasks/02_AUDIO_PIPELINE.md` Phase C: `샘플 음성 사용`(API key 불필요, offline TTS 합성 데모) →
  화자 역할 확인 → 구조화/환자 설명(sidecar fixture) → 승인·공개까지 전체 흐름 (완료).
  임의 업로드 파일은 ASR provider가 없으면 `ASR_NOT_CONFIGURED`로 명확히 표시하고
  전사문 직접 입력으로 계속 진행 가능 (manual fallback).
- `tasks/02_AUDIO_PIPELINE.md` Phase D: 실제 provider 연동 (완료, 코드/mock 기반 contract test까지 —
  아래 "Phase D 실제 provider 사용법" 참고)
  - 텍스트 LLM: OpenAI (`structure_transcript`/`patient_explanation`, structured output)
  - ASR: sherpa-onnx 로컬 Whisper + pyannote 화자분리 + Silero VAD (OpenAI 아님, 오프라인)
- Phase E(실 API key로 end-to-end 실행 검증)는 아직 미실행 — 아래 참고

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
2. 입력 방법 선택:
   - `샘플 음성 사용`: API key 없이 바로 시작. 버튼 클릭 시 합성 진료 음성으로 즉시 화자분리까지
     실행되고 역할 확인 화면으로 이동
   - `내 컴퓨터에서 음성파일 선택`: wav/mp3/mp4/mpeg/mpga/m4a/webm 업로드 → 원본 재생 확인 →
     `원본 유지`/`가벼운 소음처리` 선택 후 `전처리 시작` → 표준화된 결과 재생·원본과 비교 →
     (ASR key가 없으므로) `전사문 직접 입력` 탭으로 전환해 계속 진행
   - `전사문 직접 입력`: 텍스트 입력 → 제출
3. (음성 입력의 경우) 화자 A/B의 역할을 의사/환자/보호자 중에서 확인 → `역할 확인 및 계속 처리`
4. 구조화/환자 설명 확인 (샘플은 sidecar fixture의 고정 Demo 결과)
5. 필요시 내용 수정 → 승인
6. 공개하기 → 표시된 `/p/{token}` 링크가 환자용 페이지

## 테스트

```bash
make test          # pytest (unit/contract/integration, apps/api + tests/integration) + vitest (apps/web)
make e2e           # Playwright 브라우저 E2E (API+Web 자동 기동)
make eval          # 합성 golden set에 대해 mock pipeline grounding 검사
make lint          # ruff (api) + eslint + tsc --noEmit (web)
make sample-audio  # tests/fixtures/audio/* 재생성 (offline TTS + ffmpeg, 외부 API 없음)
```

## 디렉터리 구조

```text
apps/
├── web/                 # Next.js 클라이언트. DB/LLM을 직접 호출하지 않고 apps/api만 호출한다.
└── api/
    ├── app/
    │   ├── audio/         # ffprobe 검증, ffmpeg 표준화/denoise, 서버생성 경로 기반 저장
    │   ├── domain/       # 상태 모델, 상태전이 규칙, 에러 코드, DiarizedSegment/PipelineRun
    │   ├── pipeline/      # structure_encounter / generate_patient_explanation / validate_grounding
    │   ├── providers/     # LLMProvider·ASRProvider 경계 + Mock/Demo/Unavailable 구현체
    │   ├── repositories/  # SQLite 저장 (encounter/version/audit/audio_assets/pipeline_runs)
    │   └── routes/        # /encounters/*, /encounters/*/audio*, /system/capabilities,
    │                      # /public/explanations/{token}
    └── tests/             # unit + contract (mock 출력 vs JSON schema, ffprobe/ffmpeg 검증)
packages/contracts/schema/ # ClinicalStructure / ExplanationDraft JSON schema
scripts/
└── generate_sample_audio.py  # make sample-audio가 호출하는 offline TTS 생성 스크립트
tests/
├── fixtures/
│   └── audio/   # sample_consultation.wav + transcript/structure/explanation sidecar (합성)
├── integration/ # API+SQLite, 접근제어, 승인 불변성, 오디오 파이프라인
├── e2e/         # Playwright
└── evals/       # make eval 스크립트
```

## 환경변수

`.env.example` 참고. 기본값은 모두 로컬 demo 모드(외부 API 없음)로 동작하도록 되어 있다.

## Phase D 실제 provider 사용법

**텍스트 LLM (OpenAI)** — `apps/api/.env.local`에 아래만 넣으면 된다 (이미 파일이 있다고 하셨으니
`ARIAD_MODE`/`OPENAI_API_KEY` 두 줄만 추가하면 됨):

```dotenv
ARIAD_MODE=provider
OPENAI_API_KEY=sk-...실제키...
OPENAI_TEXT_MODEL=gpt-4o-mini   # 비워두면 기본값 gpt-4o-mini 사용
```

`apps/api/.env.local`은 `.gitignore`에 이미 포함되어 있어 git에 올라가지 않는다. 프론트엔드
(`apps/web/.env.local`)에는 절대 key를 넣지 않는다 — `NEXT_PUBLIC_*`는 브라우저 번들에
그대로 노출되기 때문에, 프론트엔드 코드는 key를 볼 수 있는 구조 자체가 아니다.

**ASR (sherpa-onnx, 로컬)** — OpenAI가 아니라 오프라인 Whisper+화자분리+VAD 조합을 쓴다
(임상의가 제공한 `asr_pipeline.py` 기반). 모델 파일은 이 저장소에도, pip 패키지에도 포함되어
있지 않다 — GitHub Releases에서 직접 받아야 한다:

```bash
mkdir -p apps/api/models
cd apps/api/models
# https://github.com/k2-fsa/sherpa-onnx/releases 에서:
#   sherpa-onnx-whisper-large-v3.tar.bz2       -> 압축 해제 (encoder/decoder/tokens)
#   sherpa-onnx-pyannote-segmentation-3-0.tar.bz2 -> 압축 해제
#   3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx -> emb.onnx로 이름 변경
#   silero_vad.onnx
```

최종 구조는 `.env.example`의 `ARIAD_SHERPA_MODELS_DIR` 주석에 정확히 적혀 있다. 받은 뒤
`apps/api/.env.local`에 `ARIAD_SHERPA_MODELS_DIR=./models` (기본값, apps/api 기준 상대경로)를
추가하면 된다. `make doctor`는 ffmpeg/ffprobe/espeak-ng만 확인하며, sherpa-onnx 모델 존재
여부는 `GET /system/capabilities`의 `asr` 필드(`"local"` = 모델 있음, `"unavailable"` = 없음)로
확인한다.

**동작 확인**

```bash
make dev
# 브라우저에서: 내 컴퓨터에서 음성파일 선택 → 업로드 → (모델이 있으면) 전사 시도 버튼으로
#              실제 화자분리+전사 실행. 역할 확인 → 처리 시작 시 실제 OpenAI로 구조화/설명 생성.

make test-provider-audio AUDIO=tests/fixtures/audio/sample_consultation.wav
# 실제 provider(로컬 ASR은 무료, OpenAI 텍스트 단계는 유료 — 진행 전 y/N 확인받음)로
# 커맨드라인에서 직접 검증. make test/make e2e에는 포함되지 않는다(비용 없음, mock으로 검증).
```

## 알려진 제한

- 실제 ASR provider(OpenAI 등) 연동 없음 — `샘플 음성 사용`만 즉시 동작(Demo, sidecar fixture
  기반), 임의 업로드 파일은 ASR 없이는 전사되지 않고 `ASR_NOT_CONFIGURED`로 안내됨 (Phase D 이후)
- 실 로그인 없음 (단일 고정 clinician으로 간주, API 인증 없음)
- 승인된 면담이 `PUBLISHED` 상태일 때는 수정이 불가하다 (먼저 `공개 취소` 후 편집).
  `APPROVED`(공개 전) 상태에서의 편집만 지원.
- CORS는 로컬 개발 origin(`http://localhost:3000`)만 허용하도록 고정되어 있다.
- `ffmpeg`/`ffprobe`가 시스템에 설치되어 있어야 오디오 업로드가 동작한다
  (`make doctor`로 확인, 없으면 `sudo apt-get install -y ffmpeg`).

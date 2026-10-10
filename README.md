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
- `tasks/03_SPEAKER_MERGE_AND_LATENCY.md` Phase 1: pipeline stage별 latency 계측(`stage_runs` 테이블) +
  real provider 인스턴스 캐싱(요청마다 재생성되던 문제 수정) + `make benchmark-audio` (완료).
  실측 결과 모델 재로딩은 병목이 아니었고 `asr_inference` 자체가 RTF ~2.6x로 거의 전부를 차지함이
  확인됨 → `make diagnose-asr`/`make compare-asr-accuracy`로 원인 분해 후, "auto→ko 이중 디코딩"이
  실제 원인임을 실측(속도 + 정확도)으로 확인하고 `ko_mode` 기본값을 `ko_only`로 전환(완료, 아래
  "ASR ko_mode 기본값 전환" 참고). Phase 2 이후(수동 화자 병합, 자동 병합 추천)는 아직 미착수 —
  실측 중 발견된 화자분리 한계는 "알려진 제한" 참고.
- `tasks/04_CLINICAL_ENRICHMENT.md`: ASR 전사문과 structure_llm 사이에 "임상 의미 정리" 단계 추가
  (완료, 아래 "임상 의미 정리 (clinical enrichment)" 참고). 원문 보존 + 근거 연결 + 4가지 금지
  패턴(근거 없는 점수/진단, 질문의 소견화, 부정 반전) 회피를 기계적 validator로 강제. 실제 OpenAI
  품질 측정은 이 환경에 API key가 없어 미실행 — `--real` 플래그로 사용자가 직접 실행 필요.

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
make eval          # 합성 golden set grounding 검사 + clinical enrichment 안전성/추출 평가
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

**텍스트 LLM (OpenAI)** — `apps/api/.env.local`에 아래만 넣으면 된다. `make dev`가
`uvicorn --env-file apps/api/.env.local`로 이 파일을 자동으로 읽는다 (파일이 없으면 조용히
무시되고 demo 모드로 동작 — 기존 사용자에게 영향 없음):

```dotenv
ARIAD_MODE=provider
OPENAI_API_KEY=sk-REPLACE_WITH_YOUR_REAL_KEY
OPENAI_TEXT_MODEL=              # 비워두면 기본값 gpt-4o 사용 (비용을 줄이려면 gpt-4o-mini)
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

최종 구조는 `.env.example`의 `ARIAD_SHERPA_MODELS_DIR` 주석에 정확히 적혀 있다. 위 명령대로
`apps/api/models/`에 받아두면 그걸로 끝이다 — `ARIAD_SHERPA_MODELS_DIR`은 `.env.local`에 직접
적을 필요 없다. `make dev`/`make test-provider-audio`/`make benchmark-audio`가 각각
`./apps/api/models`(repo root 기준 상대경로)를 스스로 넣어준다. 이 스크립트들은 항상 repo
root를 작업 디렉터리로 실행되므로, `.env.local`에 apps/api 기준 상대경로(예: `./models`)를
따로 적으면 오히려 잘못된 경로로 해석되어 `모델 파일을 찾을 수 없습니다` 오류가 난다 — 정말
기본값과 다른 경로를 쓰고 싶을 때만 `.env.local`에 **절대경로**로 적어라. `make doctor`는
ffmpeg/ffprobe/espeak-ng만 확인하며, sherpa-onnx 모델 존재 여부는 `GET /system/capabilities`의
`asr` 필드(`"local"` = 모델 있음, `"unavailable"` = 없음)로 확인한다.

**동작 확인**

```bash
make dev
# 브라우저에서: 내 컴퓨터에서 음성파일 선택 → 업로드 → (모델이 있으면) 전사 시도 버튼으로
#              실제 화자분리+전사 실행. 역할 확인 → 처리 시작 시 실제 OpenAI로 구조화/설명 생성.

make test-provider-audio AUDIO=tests/fixtures/audio/sample_consultation.wav
# 실제 provider(로컬 ASR은 무료, OpenAI 텍스트 단계는 유료 — 진행 전 y/N 확인받음)로
# 커맨드라인에서 직접 검증. make test/make e2e에는 포함되지 않는다(비용 없음, mock으로 검증).

make benchmark-audio AUDIO=tests/fixtures/audio/sample_consultation.wav RUNS=3
# tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1 baseline. ASR을 1회 cold + RUNS회 warm
# 실행해 stage별(asr_preprocess/asr_model_load/asr_inference) cold/warm median/min/max를
# 표로 출력한다 (OPENAI_API_KEY가 있으면 structure_llm/explanation_llm도 이어서, y/N 확인 후).
# 이것도 make test/make e2e에는 포함되지 않는다.

make diagnose-asr AUDIO=tests/fixtures/audio/sample_consultation.wav
# asr_inference 내부를 더 잘게 쪼갠다 (Phase 1 후속): diarization 시간, recognizer_auto/
# recognizer_ko 각각의 호출 횟수·누적 시간·입력 오디오 길이, turn별 세부 표, RTF를 출력한다.
# 녹음 내용/전사문은 출력하지 않는다. cold 1회(모델 warm-up) + warm 1회 실행, 무료(로컬 ASR만).

# ko_mode 비교 (아래 실측 결과에 따라 ko_only가 기본값):
ARIAD_ASR_KO_MODE=auto_then_ko make diagnose-asr AUDIO=tests/fixtures/audio/sample_consultation.wav
ARIAD_ASR_KO_MODE=ko_only      make diagnose-asr AUDIO=tests/fixtures/audio/sample_consultation.wav
# env var 생략 시 ko_only(기본값)와 동일하게 동작한다.

# 스레드 수 비교(CPU 코어가 적거나 많은 환경에서 diarize/decode에 영향이 있는지 확인):
ARIAD_SHERPA_NUM_THREADS=2 make diagnose-asr AUDIO=tests/fixtures/audio/sample_consultation.wav
ARIAD_SHERPA_NUM_THREADS=4 make diagnose-asr AUDIO=tests/fixtures/audio/sample_consultation.wav
# 생략 시 os.cpu_count() 기본값을 그대로 쓴다(동작 변경 없음, 실측 근거 없어 기본값 유지).

make compare-asr-accuracy
# tasks/03_SPEAKER_MERGE_AND_LATENCY.md item 4: 속도(RTF)만으로 ko_mode를 채택하지
# 않기 위한 정확도 비교. sample_consultation 기존 ground truth(약명 리시노프릴, 용량
# 5mg, 부정 표현 "아스피린 미투여", 날짜 "시월 첫째 주", 화자 A=doctor/B=patient)를
# 기준으로 auto_then_ko/ko_only 각각의 RTF + 화자분리 일치율 + 임상 anchor pass/fail +
# 세그먼트별 expected/predicted 텍스트를 나란히 출력한다. 비교 대상은 KO_MODES=a,b로
# 바꿀 수 있다(기본값: auto_then_ko,ko_only). 합성 fixture만 사용, 무료(로컬 ASR만),
# make test/make e2e에는 포함되지 않는다.
```

**ko_mode 기본값 전환 (실측 완료, 2026-09-27)**: 사용자가 실제 하드웨어에서
`sample_consultation.wav`(59.54s)로 `make diagnose-asr`와 `make compare-asr-accuracy`를
모두 실행해 확보한 실측 결과:

| ko_mode      | RTF        | 정확도 (임상 anchor 4개 중) | 비고 |
|--------------|------------|------------------------------|------|
| auto_then_ko | 2.64–2.69x | 0/4 pass                     | auto 인식기가 언어를 잘못 판별해 완전히 깨진 로마자 표기 환각(hallucination) 텍스트 생성. 자체 비-한국어 판별 fallback도 로마자 환각은 못 걸러냄 |
| ko_only      | 1.27–1.35x | 1/4 pass                     | 읽을 수 있는 한국어로 정상 디코딩(나머지 3개 실패는 mode 문제가 아니라 순수 ASR 인식 오류, 예: "오 밀리그램"→"오오 밀크 레") |

**ASR 출력 검증 단 + 제2단 설계 (tasks/06_ASR_OUTPUT_VERIFICATION.md,
2026-10-07)**: `make compare-asr-accuracy`가 이제 4개 anchor PASS/FAIL뿐
아니라 전체 전사문 기준 CER/WER(`app/eval/asr_metrics.py`)도 함께
출력한다 — 세그먼트별 숫자가 아니라 **whole-transcript 숫자를 믿을 것**
(이 fixture는 diarization이 10개 세그먼트를 1개로 병합해서 세그먼트별
비교는 의미가 없다는 게 사용자 실측으로 확인됐고, 그래서 whole-transcript
비교로 고쳤다). 또한 ASR 이후 출력을 개선하는 후처리 두 가지가
opt-in으로 준비됐다(아직 어떤 provider에도 연결 안 됨):
`app/pipeline/asr_normalize.py`(단위어 바로 앞 숫자만 정규화, "오
밀리그램"→"5 밀리그램") / `app/pipeline/medication_candidates.py`(약명
사전 fuzzy 교정 후보 — 원문은 안 바꾸고 `needs_review` 후보만 제시).

```bash
make vital-signs-audio
# tasks/06의 "leading-keyword anchor"(혈압처럼 숫자 앞에 오는 키워드) 연구용
# 합성 fixture 생성. tests/fixtures/audio/vital_signs_dictation.wav(53.3s,
# 12 세그먼트) + .transcript.json. 혈압/체중/혈당/맥박/소수점 체온 등 다양한
# 어순 패턴 포함(세그먼트별 vital_sign_pattern 메타데이터로 표시).

AUDIO=tests/fixtures/audio/vital_signs_dictation.wav \
GROUND_TRUTH=tests/fixtures/audio/vital_signs_dictation.transcript.json \
make compare-asr-accuracy
# 위 fixture로 실제 ASR이 혈압/체중 등을 어떻게 깨뜨리는지 관찰(사용자
# 하드웨어 필요). 이 fixture에는 기존 4개 anchor가 없어 전부 [SKIPPED]로
# 표시된다 — 정상 동작.
```

**실측 결과(2026-10-09)**: 위 fixture로 실제 돌려보니 숫자 5개(138/86,
72, 118, 76, 132/84/70)가 전부 사라졌다(단순 "깨짐"이 아니라 숫자 음절
자체가 안 나타남) — `espeak-ng -v ko -x`로 TTS 발음 자체는 정확함을
확인했으니 TTS 문제는 아니다. 디코딩 구간 길이(merge_diarization_turns의
28초 분할)와 관련 있을 가능성을 검증하는 추가 fixture를 만들었다:

```bash
make vital-signs-isolated-audio
# 숫자 포함 문장 6개를 각각 2.0초 간격으로 격리(merge_diarization_turns의
# merge_gap_seconds=0.8초보다 길게 둬서 재병합을 막음) -- 각 문장이 짧은
# 단독 구간으로 디코딩되는지, 그러면 숫자가 돌아오는지 확인하는 진단용.

AUDIO=tests/fixtures/audio/vital_signs_isolated.wav \
GROUND_TRUTH=tests/fixtures/audio/vital_signs_isolated.transcript.json \
make compare-asr-accuracy
make diagnose-asr AUDIO=tests/fixtures/audio/vital_signs_isolated.wav  # 실제 구간 개수 확인
```

자세한 분석과 결과 해석 방법은 tasks/06_ASR_OUTPUT_VERIFICATION.md 참고.

RTF·정확도 두 지표 모두 `ko_only`가 확인된 개선이므로(속도만으로 채택하지 않는다는
원칙 충족) **`ko_only`를 기본값으로 전환했다** (`ARIAD_ASR_KO_MODE` 생략 시 `ko_only`).
`auto_then_ko`는 다국어 시나리오 참고용으로 env var를 통해 여전히 선택 가능하지만,
이 한국어 전용 임상 대화 사용 사례에는 더 이상 권장하지 않는다.

`ARIAD_SHERPA_NUM_THREADS`는 여전히 opt-in 진단용 플래그로 남아 있다 — 스레드 수가
실측으로 유의미한 차이를 보인다는 근거는 아직 없어 기본값(`os.cpu_count()`)을 유지한다.

## ASR 하드웨어/엔진 실측 (tasks/05_ASR_HARDWARE_SPEEDUP.md)

실제 6분 녹음이 14분 걸린 문제(목표: 10분 녹음 → 60초 이내, RTF ≤ 0.1)를 진단하고
GPU/모델 후보를 비교하기 위한 도구. **이 저장소의 개발 환경에는 GPU가 없고 실제
녹음 파일/모델도 없어 실측을 대신 실행해 줄 수 없다 — 아래 명령을 사용자 PC에서
직접 실행해야 한다.**

```bash
make detect-asr-hardware
# CPU 모델/물리 코어/RAM, GPU 제조사/모델/VRAM/드라이버(nvidia-smi/rocm-smi, 없으면
# 없다고 명시), sherpa-onnx의 provider(cpu/cuda/coreml) 지원 여부, faster-whisper
# 설치 여부, 모델 파일 양자화(int8) 여부, num_threads 해석값을 출력한다. 실제 오디오/
# 모델 불필요, 수 초 내 실행, 항상 안전.

make diagnose-asr AUDIO=path/to/recording.wav
# 이제 diarize_ms/vad_ms(신규)/auto/ko/postprocess_ms(신규)를 모두 분리해서 보여준다
# (이전에는 VAD와 후처리 시간이 어디에도 측정되지 않고 있었다). provider/ko_mode/
# num_threads 현재 설정도 함께 출력한다.

ARIAD_SHERPA_PROVIDER=cuda make diagnose-asr AUDIO=path/to/recording.wav
# GPU 경로 시도(opt-in, 기본값은 여전히 cpu). sherpa-onnx의 from_whisper()는 provider=
# "cuda"를 구조적으로 받아들이지만, 실제로 CUDA execution provider가 빌드에 포함돼
# 있는지는 별개 문제다 -- 아래 compare-asr-engines가 "생성 성공"과 "실제 GPU 사용"을
# 구분해서 알려준다.

make compare-asr-engines AUDIO=path/to/recording.wav
# 같은 파일에 대해 여러 엔진/provider 후보를 순서대로 실행하고 비교한다:
#   sherpa_whisper_cpu / sherpa_whisper_cuda (기존 엔진, provider만 바꿈)
#   sherpa_sensevoice_cpu / sherpa_sensevoice_cuda (sherpa-onnx 기본 지원, 별도
#     SenseVoice 모델 다운로드 후 ARIAD_SENSEVOICE_MODEL/ARIAD_SENSEVOICE_TOKENS 설정 필요)
#   faster_whisper_cpu_int8 / faster_whisper_cuda_fp16 (선택 설치:
#     apps/api/.venv/bin/pip install faster-whisper, FASTER_WHISPER_MODEL로 모델 크기 지정)
# 각 후보의 warm decode 시간과 RTF뿐 아니라, decode 도중 별도 스레드로 샘플링한
# GPU 사용률/VRAM/CPU 사용률(평균·최대)을 함께 출력한다 -- GPU가 "구성상 인식"됐다는
# 것과 "실제로 그 위에서 연산이 돌았다"는 것을 구분하기 위함이다. 설치/모델이 없는
# 후보는 조용히 빠지지 않고 이유와 함께 SKIPPED로 표시된다. ENGINES=a,b로 특정
# 후보만 골라 실행할 수 있다.

make check-faster-whisper-accuracy
# 속도(RTF)만으로 엔진을 채택하지 않기 위한 정확도 비교. sample_consultation.wav
# 기존 ground truth(약명/용량/부정/날짜, make compare-asr-accuracy와 동일 anchor)로
# faster-whisper의 한국어 임상 전사 품질을 확인한다. 합성 fixture만 사용(실제 녹음
# 내용은 출력하지 않음, 애초에 이 스크립트는 실제 녹음을 받지도 않는다).
# apps/api/.venv/bin/pip install faster-whisper 필요. FASTER_WHISPER_MODEL로
# 모델 크기(기본 small) 조정 가능 -- large-v3/turbo 등도 시험해볼 것.

make parallel-asr-diarization AUDIO=path/to/recording.wav
# ASR(faster-whisper, GPU)과 화자분리(sherpa-onnx, CPU)를 순차 실행과 동시 실행
# (threading.Barrier로 같은 순간에 시작)으로 둘 다 돌려 비교한다. 각 작업의
# 시작/종료 시각을 공유 기준점 대비로 출력해 실제로 겹쳤는지 직접 확인할 수 있다.
# FASTER_WHISPER_MODEL(기본 large-v3)/ARIAD_SHERPA_PROVIDER(기본 cpu, 화자분리에는
# 변경 비권장 — 이미 GPU가 더 느림을 확인함)로 조정 가능.
#
# 실측 결과(2026-10-04): speedup 1.00x — 스레드로는 효과 없음. overlap window는
# 컸지만("둘 다 시작됨" 상태가 전체 구간과 겹쳤음) 실제로는 diarization이 GIL을
# 계속 쥐고 있어 ASR이 그 끝날 때까지 거의 진행하지 못한 것으로 보임(ASR 스레드의
# 종료 시각이 diarize 종료 시각 + ASR 단독 소요시간과 거의 일치). overlap window
# 크기만으로 "병렬화가 됐다"고 판단하면 안 된다는 것도 이번에 배운 것 — 판정은
# speedup(순차 대비 실제로 빨라졌는지)으로만 한다.

make parallel-asr-diarization-mp AUDIO=path/to/recording.wav
# 위 결과(스레드 효과 없음) 이후 시도: 공유 GIL이 없는 별도 OS 프로세스로 같은
# 실험을 재시도한다. 각 프로세스가 자기 모델을 따로 로드/워밍업한 뒤
# multiprocessing.Barrier로 동시에 시작한다. CUDA와 fork를 섞으면 위험해
# "spawn" 방식을 명시적으로 쓴다. 같은 run 안에서 단일 프로세스 순차 베이스라인도
# 함께 측정해 직접 비교한다(베이스라인 모델은 VRAM 확보를 위해 자식 프로세스
# 시작 전에 명시적으로 해제).
#
# 실측 결과(2026-10-04, 6분 실제 파일): speedup 1.44x(RTF 0.243 -> 0.169) --
# 별도 프로세스에서는 실제로 효과가 있었다(스레드는 1.00x). diarize/asr 둘 다
# 단독 실행과 거의 같은 속도로 동시에 끝남(오버헤드 1% 내외) -- GIL이 스레드
# 버전의 원인이었다는 가설이 그대로 확인됨. 10분 환산 ~101초(목표 60초의 1.7배).

make compare-diarization-engines AUDIO=path/to/recording.wav
# tasks/05 Path C: diarization 자체 가속 조사. sherpa-onnx CPU 베이스라인
# (CUDA는 이미 더 느림을 확인함) 대 pyannote.audio(PyTorch 기반, sherpa-onnx의
# C++ diarization이 원래 포팅된 원본 구현 -- 진짜 CUDA 가속을 받을 수 있다는
# "가설", 이 환경에서 실측된 적은 없음)를 비교한다. pyannote.audio 설치
# (`pip install pyannote.audio`) + HuggingFace 토큰(HUGGINGFACE_TOKEN 또는
# HF_TOKEN) + pyannote/speaker-diarization-3.1·pyannote/segmentation-3.0 각각의
# gated 라이선스 동의가 필요하다 -- huggingface.co에서 로그인 후 두 모델
# 페이지에서 "Agree and access" 후 Settings > Access Tokens에서 토큰 발급.
# 미설치/미동의/GPU 없음은 각각 다른 이유로 SKIPPED 처리되어 출력된다
# (fabricate하지 않음). ENGINES=sherpa_cpu,pyannote_cuda 등으로 후보 선택 가능.
```

**경로 B 실제 파이프라인 적용 (`ARIAD_ASR_ENGINE`, opt-in)**: 위 `make
parallel-asr-diarization-mp`로 실측 확인된 프로세스 기반 병렬 실행이
`app/providers/parallel_asr.py`(`ParallelASRProvider`)로 실제 파이프라인에
들어갔다. 기본값은 변경되지 않았다 — `ARIAD_SHERPA_MODELS_DIR`가 가리키는
sherpa-onnx 모델 + `ARIAD_ASR_ENGINE`(기본 `sherpa`)를 그대로 두면 기존
`SherpaOnnxASRProvider`(순차 실행)가 그대로 쓰인다. `ARIAD_ASR_ENGINE=
parallel_fw_cuda`로 명시적으로 켜야 diarization(sherpa-onnx, CPU)과
ASR(faster-whisper large-v3, CUDA)이 별도 프로세스로 동시에 돈다
(`apps/api/.venv/bin/pip install faster-whisper` 필요 -- 설치돼 있지 않으면
전사 시도 시 `ASR_PROVIDER_FAILED`로 명확히 안내됨, 조용히 다른 엔진으로
넘어가지 않음). **실측으로 발견/수정된 버그**: `make dev`(uvicorn --reload)
밑에서 `parallel_fw_cuda`로 실제 전사를 돌리면 ASR worker 프로세스가
`libcublas.so.12 is not found` 에러로 실패하는 사례가 있었다 — 같은 CUDA
호출이 평범한 스크립트 실행에서는 됐던 것과 달리, 이 중첩된 worker
프로세스는 대화형 셸의 `LD_LIBRARY_PATH`를 그대로 물려받지 못한 것으로
보인다. `_ensure_cuda_libs_on_path()`가 `nvidia-cublas-cu12`/
`nvidia-cudnn-cu12` pip 패키지의 실제 경로를 코드로 찾아 추가하도록
수정했다(셸 상속에 의존하지 않음) — 자세한 내용과 재현 방법은 tasks/05의
"실측 업데이트" 절 참고. **아직 기본값으로 올리지 않은 이유**: `make
check-faster-whisper-accuracy FASTER_WHISPER_MODEL=large-v3`로 실측했을 때
large-v3가 실제 부정 표현("시작하지 않습니다" -> "시작하기란 습니다")을
누락하는 사례가 확인됐다 -- 속도 개선과 별개로 임상 안전성 하류 검증
(`apps/api/app/pipeline/enrichment_validation.py`의 부정 가드 강화 등)이
선행돼야 기본값 전환을 고려할 수 있다.

**측정 순서 제안** (tasks/05 item 4): `sample_consultation.wav`(59.5s, 이미 있음) →
기존 6분 녹음 → 가능하면 ~10분 녹음. 한 번에 하나의 ASR 시험만 실행할 것(CPU/GPU
점유가 겹치면 서로의 숫자를 왜곡한다). 이 환경에는 실제 6분/10분 녹음이 없으므로
그 실측치는 사용자가 직접 채워야 한다 — 녹음/전사 결과 자체는 저장소에 커밋하지
말 것(합성 데이터만 커밋).

**문제 해결**

- `ModuleNotFoundError: No module named 'openai'` (또는 `sherpa_onnx`) — Phase D에서
  `requirements.txt`에 새 의존성이 추가됐다. 기존 `.venv`를 그대로 쓰고 있다면
  `apps/api/.venv/bin/pip install -r apps/api/requirements-dev.txt` (또는 `make setup` 재실행)로
  다시 설치해야 한다.
- `make e2e`에서 `browserType.launch: ... executable doesn't exist` — 로컬에 Playwright용
  Chromium이 설치되어 있지 않은 것이다. `npx playwright install chromium`을 한 번 실행하면 된다
  (관리형 클라우드 샌드박스에서는 미리 설치된 Chromium 경로를 자동으로 사용하므로 이 단계가
  필요 없다).

## 임상 의미 정리 (clinical enrichment)

`tasks/04_CLINICAL_ENRICHMENT.md`: ASR 전사문(`PipelineRun.segments`, 화자 role 확인
후)과 기존 `structure_llm` 사이에 추가된 단계다. 원본 전사문/`ClinicalStructure`는
전혀 건드리지 않고, `EncounterVersion.enrichment`(nullable, additive)에 약물/증상/
진찰/진단/계획 후보를 각각 원문 구절(`source_spans`)에 연결해 별도로 저장한다.
세그먼트 단위 화자/시각 정보가 없는 수동 텍스트 입력이나 demo 모드에서는 `null`이다.

```bash
apps/api/.venv/bin/python scripts/eval_clinical_enrichment.py
# sample_consultation(59.5s)과 clinical_dialogue_3min(합성, ~155s, 3화자, 오디오 없음
# 텍스트 전용 fixture) 양쪽에 대해 mock provider로 안전성(4가지 금지 패턴 회피)과 실제
# 항목 추출 커버리지를 함께 출력한다. 무료, make test/make e2e에는 포함되지 않지만
# make eval에는 포함됨(golden set grounding 검사 다음에 자동 실행).

apps/api/.venv/bin/python scripts/eval_clinical_enrichment.py --real
# OPENAI_API_KEY가 있으면 실제 LLM으로 같은 평가를 실행한다(비용 발생, y/N 확인 후).
# 이 개발 환경에는 API key가 없어 이 스크립트를 만든 사람이 직접 실행해 본 적은 없다 —
# 실제 추출 품질은 사용자가 이 명령으로 직접 확인해야 한다.
```

**mock provider의 알려진 한계**: 기본 `ARIAD_MODE=mock`의 `MockLLMProvider._clinical_
enrichment`는 규칙(정규식) 기반이라 안전성(금지 패턴 회피)은 구조적으로 보장하지만
커버리지는 제한적이다 — 예를 들어 "아스피린은... 중단했고..." 같은 표현은 "약"이라는
글자가 없어 의약품으로 인식되지 않는다(위 eval 결과의 FAIL 항목 참고). 실제 LLM(OpenAI)
을 쓰면 이런 경우도 잡아낼 가능성이 높지만, 그 품질은 이 환경에서 실측하지 못했다.

**item 7(3~10분 대화 → 1분 미만 정리) 실측 여부**: enrichment 단계 자체는 mock 기준
1ms 미만이라 무시할 수 있는 수준이지만, 목표는 전체 파이프라인(ASR+enrichment+구조화+
설명)을 가리키는 것으로 이해했고, 지배적 비용은 실제 LLM 응답 시간일 것으로 예상된다.
이 환경에서는 실제로 측정하지 못했다 — `--real` 실행 후 `stage_runs` 테이블의
`clinical_enrichment_llm`/`structure_llm`/`explanation_llm` 행 duration_ms 합으로
직접 확인해야 한다.

## 알려진 제한

- 실제 ASR provider(OpenAI 등) 연동 없음 — `샘플 음성 사용`만 즉시 동작(Demo, sidecar fixture
  기반), 임의 업로드 파일은 ASR 없이는 전사되지 않고 `ASR_NOT_CONFIGURED`로 안내됨 (Phase D 이후)
- 실 로그인 없음 (단일 고정 clinician으로 간주, API 인증 없음)
- 승인된 면담이 `PUBLISHED` 상태일 때는 수정이 불가하다 (먼저 `공개 취소` 후 편집).
  `APPROVED`(공개 전) 상태에서의 편집만 지원.
- CORS는 로컬 개발 origin(`http://localhost:3000`)만 허용하도록 고정되어 있다.
- `ffmpeg`/`ffprobe`가 시스템에 설치되어 있어야 오디오 업로드가 동작한다
  (`make doctor`로 확인, 없으면 `sudo apt-get install -y ffmpeg`).
- **clinical enrichment 결과를 검토/수정하는 프론트엔드 UI가 없다** — `EncounterVersion.
  enrichment`는 API 응답(JSON)에는 포함되지만, 지금은 `apps/web`에서 화면에 표시하거나
  의료진이 후보를 선택/수정하는 인터랙션이 없다. 의도적으로 이번 범위 밖으로 뒀다
  (tasks/04_CLINICAL_ENRICHMENT.md는 백엔드 단계 설계·구현까지만 요청됨) — 후속 작업.
- **화자분리(diarization)가 `sample_consultation.wav` 합성 fixture에서 두 화자를 구분하지
  못함** — `make diagnose-asr`/`make compare-asr-accuracy` 실측 중 발견: ko_mode와 무관하게
  59.54초 전체가 diarizer의 최종 병합 후 단일 화자 라벨 1개 segment로만 반환됨(원본 diarization은
  3개 turn을 만들었지만 전부 같은 speaker_index로 판별되어 `merge_adjacent_same_speaker`가 하나로
  합침). 두 화자 모두 같은 TTS 엔진/보이스로 합성된 `scripts/generate_sample_audio.py` fixture의
  음향 특성이 pyannote 임베딩 기준으로 구분하기에 너무 유사하기 때문일 가능성이 높다 — 실제 두
  사람의 음성이 섞인 오디오에서도 같은 문제가 재현되는지는 미확인. `tasks/03_SPEAKER_MERGE_AND_LATENCY.md`
  Phase 2(수동 화자 병합/재배정 UI)의 전제조건이므로, Phase 2 착수 전에 실제(또는 최소한 서로 다른
  보이스로 합성한) 다화자 샘플로 diarization 자체를 별도 검증할 필요가 있다. 이번 task 03 범위(ASR
  지연 최적화)에서는 원인 분석만 하고 수정하지 않았다 — ko_mode 선택과 무관한 별개 결함이기 때문.

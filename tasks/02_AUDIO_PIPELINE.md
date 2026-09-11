# Task 02: Replayable audio pipeline

## Outcome

합성 음성파일이 단계별 artifact와 상태를 남기며 preprocess→mock ASR→mock diarization→role confirmation까지 처리되고, 실패 단계를 독립적으로 재실행할 수 있다.

## Read first

- `docs/AI_PIPELINE.md`
- `docs/DEBUGGING.md`
- `docs/TESTING_AND_EVALS.md`

## In scope

- 지원 audio format과 size validation
- ffmpeg 기반 mono/16 kHz 변환과 loudness normalization
- `off|light` denoise 설정의 자리만 마련하되 검증되지 않은 denoiser는 추가하지 않음
- typed ASR/Diarization provider interface와 deterministic mock
- speaker A/B/C와 doctor/patient/guardian/unknown role 분리
- confidence 낮을 때 manual confirmation
- stage run, hash, version, duration, error code 저장
- 합성 artifact로 stage replay와 JSON diff

## Out of scope

- 실제 cloud ASR/diarization provider
- live streaming, biometric speaker identification
- 운영환경 원음 보존정책 확정
- worker/queue 분리

## Acceptance criteria

- 고정 합성 audio fixture가 같은 canonical stage output을 만든다.
- 잘못된 codec과 빈 transcript가 다른 error code를 낸다.
- 한 stage 실패 후 그 stage부터 재실행할 수 있다.
- low-confidence role은 자동 확정되지 않는다.
- 일반 log에 audio/transcript 본문이 없다.
- unit, integration, replay test가 통과한다.


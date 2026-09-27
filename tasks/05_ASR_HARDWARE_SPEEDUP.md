# Task 05: ASR Hardware Speedup

## 배경

`tasks/03_SPEAKER_MERGE_AND_LATENCY.md`의 ASR 지연 진단과는 별도로, 실제 녹음
파일에서 ASR이 너무 느리다는 문제를 다룬다. 59.5초 합성 파일에서 warm
asr_inference가 약 159초(RTF 약 2.7)였고, 실제 6분 녹음은 6분 넘게 처리 중이며
최종적으로 14분 안에 완료되었다.

목표: 녹음 종료 후 10분 음성의 화자 표시 전사문을 60초 이내 제공(RTF 0.1 이하).
로컬 GPU 활용, 더 빠른 모델, 추론 최적화, 파이프라인 변경을 모두 비교해 사용자가
방향을 선택할 수 있는 실측 보고서를 만든다.

## 1. 현재 병목과 하드웨어 확인

- 실제 업로드 → 전사문 반환 호출 경로 추적
- ffmpeg, VAD, 화자분리, 모델 로딩, auto decode, ko fallback, 후처리 각각의 시간과
  ASR 호출 횟수 측정
- 호출별 오디오 길이, 총 모델 입력 길이, 화자 구간 수, 중복 디코딩 길이 기록
- CPU 모델·물리 코어 수·RAM, GPU 제조사/모델·VRAM·드라이버, 실제 실행 provider,
  모델 파일의 양자화 여부와 thread 수 확인
- GPU 사용 가능하다는 표시만으로 충분하다고 판단하지 않는다 — 실제 ASR 실행 중
  GPU 사용률·VRAM과 CPU 사용률을 확인하고, 연산이 CPU로 fallback하는지도 확인
- 전사문, 환자 정보, API key는 진단 로그에 남기지 않는다
- `scripts/benchmark_audio.py`의 전역 `logging.basicConfig`는 복원하지 않는다
  (Task 03 표준 제약, 계속 유지)

## 2. 로컬 GPU 경로 비교

- NVIDIA: (A) 기존 sherpa-onnx Whisper를 CUDA provider로 (B) faster-whisper/
  CTranslate2 multilingual turbo 등을 CUDA FP16/INT8로 (C) VRAM 허용 시 VAD chunk
  GPU batch 처리
- AMD/Intel GPU: 공식 지원 Vulkan/OpenVINO 등 로컬 실행 경로 확인 후 CPU 대비 실측
- GPU 없거나 활용 불가: 그 사실과 이유를 명시하고 CPU 후보로 진행

드라이버/시스템 CUDA를 무작정 교체하지 않는다. 새 엔진은 기존 환경과 분리해
시험하고, 필요한 설치 변경과 재현 명령을 먼저 제시한다. GPU 모델 로딩 성공과
실제 ASR 가속을 구분해 보고한다.

## 3. 모델과 ML 기법 비교

기존 large-v3 기준으로 독립 후보 비교: faster-whisper CPU INT8(small/turbo 등),
SenseVoice INT8 등 경량 ASR, VAD 무음 제거/짧은 구간 반복 인식 방지, auto→ko 이중
디코딩 제거/조건부 재시도, 화자분리 전 발화 chunk 인식 후 타임스탬프로 화자 배정,
beam/batch size 변경, 2단계(빠른 1차 + 중요 구간만 재인식) 방식, 녹음 중 점진적
전사(대기시간 개선과 총 처리량 개선을 혼동하지 않음).

각 기법에서 전사 누락, chunk 경계 오류, 화자 배정 오류, 약명·용량·부정 표현
오류 가능성을 함께 검토한다. 기존 기본 경로는 유지하고 후보는 설정 플래그로
시험한다.

## 4. 공정한 실측

- 모델 로딩을 분리한 warm ASR 시간과 전체 wall time을 모두 측정
- 59.5초 → 6분 → (가능하면) 10분 순서로 시험, 동시에 다른 ASR 시험을 돌리지 않음
- ASR 완료 시간, 화자 표시 완료 시간, RTF, peak RAM/VRAM, CPU/GPU 사용률을 같은
  조건에서 비교
- faster-whisper의 segments는 끝까지 순회한 시점까지 측정
- 공개 모델 벤치마크의 배속을 이 PC의 결과로 대체하지 않는다
- 정확도는 CER뿐 아니라 약물명, 용량, 투약 횟수, 부정 표현, 좌우, 날짜, 발화 누락,
  화자 배정을 따로 비교
- 실제 녹음과 전사 결과를 저장소에 커밋하지 않는다

## 5. 결과물

숫자가 담긴 비교표: 후보 | 6분 실측 | 10분 실측(또는 명시된 환산치) | RTF | 정확도
변화 | RAM/VRAM | 추가 비용 | 구현 난도 | 주요 위험.

결론 3가지: (1) 현재 가장 큰 병목과 중복 계산 여부 (2) 현재 로컬 장비만으로
10분→1분 목표가 가능한지, 불가능하면 어떤 장비/설계 변경이 필요한지 (3) 정확도·
비용·개발 기간을 고려한 추천 경로 2개와 선택 기준.

진단 코드와 독립적인 후보 실행까지는 진행하되, 실측 보고서를 보여주기 전에는
기본 ASR 엔진을 교체하거나 외부 서버로 녹음 전송을 변경하지 않는다.

## 구현 현황 (2026-09-27)

**이 개발 환경(클라우드 샌드박스)의 실제 하드웨어**: CPU 4 vCPU(Intel Xeon
@2.8GHz, 4 physical core), RAM 15.7GB, **GPU 없음**(`nvidia-smi`/`rocm-smi`/
`lspci` 전부 없음/미검출), sherpa-onnx 모델 파일 없음, 실제 녹음 파일 없음,
`OPENAI_API_KEY` 없음. 이 환경에서는 실제 ASR 실행도, GPU 비교도, 6분/10분
실측도 물리적으로 불가능함 — 이번 구현은 **진단·비교 도구와 opt-in 후보 코드**
까지만 완료했고, 실측 자체는 사용자 PC에서 직접 실행해야 한다.

- 완료: 호출 경로 추적(README/보고 참고), `SherpaOnnxASRProvider`에 `provider`
  (cpu/cuda/coreml) opt-in 플래그 추가(기본값 cpu, 기존 동작 불변), VAD/후처리
  단계 시간을 `diagnostics`/`stage_runs`에 새로 노출(`vad_ms`, `postprocess_ms`,
  `asr_postprocess` stage), `scripts/detect_asr_hardware.py`(CPU/GPU/provider
  지원/모델 양자화/faster-whisper 설치 여부 확인, 실제 ASR 실행 불필요),
  `scripts/compare_asr_engines.py`(sherpa-onnx Whisper cpu/cuda, sherpa-onnx
  SenseVoice cpu/cuda, faster-whisper cpu-int8/cuda-fp16 -- 실제 GPU/CPU
  사용률을 백그라운드 스레드로 샘플링, "생성 성공"과 "실제 가속" 구분).
- 미완료(이 환경에서 물리적으로 불가능): 실제 6분/10분 녹음 실측, GPU 실측,
  faster-whisper/SenseVoice 실제 설치 후 정확도 비교, 최종 비교표의 숫자 채우기,
  3가지 결론의 실측 기반 확정. 사용자가 `scripts/detect_asr_hardware.py` +
  `scripts/compare_asr_engines.py`를 실행해 결과를 전달하면 이어서 채운다.

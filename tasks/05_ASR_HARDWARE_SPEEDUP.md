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

## 사용자 PC 실측 결과 (진행 중, 2026-09-28)

**하드웨어**: AMD Ryzen 5 7500F(6 physical core/12 logical), RAM 31.1GB, NVIDIA
GeForce RTX 4060 Ti(VRAM 8GB, driver 595.84). PyPI sherpa-onnx 1.13.8 wheel은
초기 상태에서 CUDA 미지원으로 확인됨(`Please compile with -DSHERPA_ONNX_ENABLE_GPU=ON
... Fallback to cpu!`) — 이후 `pip install faster-whisper`가 설치한 CUDA 런타임
공유 라이브러리(cuDNN/cuBLAS 등, 미확정이지만 유력한 원인)로 인해 sherpa-onnx의
`provider="cuda"`가 실제로 동작하기 시작한 것으로 보임(경고 사라짐, VRAM
749MB→5.7GB, RTF 대폭 개선 — 재확인됨).

**6분 실제 녹음(csw_evt.m4a, 384.73s, ko_only, num_threads=12) — sherpa-onnx CPU**:
- diarize_ms 65,234.9 / vad_ms 1,495.7 / ko 디코딩(29회) 795,772.8 / postprocess_ms 0.0
- 총 inference 862,503.4ms, **RTF 2.24x**, 이중 디코딩 없음(ko_only) — 순수 디코딩
  연산량 자체가 병목, 중복 계산 아님

**20초 클립(ariad_asr_20s.wav) — 엔진/provider 비교**:

| 후보 | RTF | warm decode | GPU 사용률(평균/최대) | VRAM peak | 비고 |
|---|---|---|---|---|---|
| sherpa_whisper_cpu | 2.358 | 47.2s | 8%/40%(배경 노이즈) | 749MB | 화자분리 포함 |
| sherpa_whisper_cuda | 0.43–0.46 | 8.7–9.2s | 33%/43% | 5703MB | 화자분리 포함, GPU 실사용 확인(경고 없음) |
| faster_whisper_cpu_int8(small) | 0.085 | 1.7s | 10%/29% | 819MB | **화자분리 미포함(ASR만)** |
| faster_whisper_cuda_fp16(small) | 0.020 | 0.41s | 84%/84% | 1536MB | **화자분리 미포함(ASR만)** |

diarize_ms(20초 클립): cpu 2105ms(RTF 0.105) / cuda 2604–2617ms(RTF ~0.13) —
diarization의 embedding 단계만 provider 적용 가능하고 segmentation 단계는
sherpa-onnx API상 provider 설정 지점이 없어(`OfflineSpeakerSegmentationPyannoteModelConfig`
에 provider 속성 없음 확인됨) GPU로 옮겨도 크게 개선되지 않음 — 오히려 약간 느려짐
(디스패치 오버헤드 추정).

**핵심 발견 (item 5-1 병목 결론에 반영)**: 화자분리 자체가 RTF 0.10~0.17을
차지한다 — ASR 디코딩을 아무리 빠르게 해도(faster-whisper+CUDA로 RTF 0.02까지
가능) 화자분리를 그대로 두면 전체 파이프라인 RTF는 0.15~0.19 수준이 되어
목표(≤0.1)를 못 채운다. **ASR 엔진 교체만으로는 목표 달성 불가 — 화자분리
자체의 재설계/가속이 필요하다.**

**버그 수정**: `scripts/compare_asr_engines.py`의 faster-whisper/SenseVoice
후보가 오디오 길이 계산에 `wave.open()`(WAV 전용)을 써서 실제 m4a 녹음에서
크래시함(`wave.Error: file does not start with RIFF id`) — ffprobe 기반
`_audio_duration_seconds()`/ffmpeg 기반 `_load_pcm_via_ffmpeg()`로 교체,
회귀 테스트 추가(`apps/api/tests/test_compare_asr_engines_audio_loading.py`,
합성 wav를 테스트 시점에 m4a로 transcode해 검증, 새 바이너리 fixture 커밋 없음).

**6분 실제 녹음(csw_evt.m4a) — faster_whisper_cuda_fp16(small), 버그 수정 후 재측정**:
- warm_decode_ms 10,196.6, **RTF 0.027**, segments 73, gpu_util 76.5%/95%(평균/최대,
  실제 GPU 포화 확인), cpu_util 15.7%/35.9%, VRAM 1,844MB. 20초 클립 결과(0.020)가
  워밍업 착시가 아니었음을 확인 — 6분 전체에서도 유지됨.

**6분 실제 녹음 — diarize_ms, provider=cuda (segmentation/embedding 전체에 cuda 강제)**:
- diarize_ms **79,821.1**(RTF 0.208) — CPU(65,234.9, RTF 0.170) **대비 22% 더 느림**
- vad_ms **6,038.1** — CPU(1,495.7) 대비 4배 느림
- sherpa 자체 ko 디코딩은 113,775.9ms(RTF 0.30)로 CPU(795,772.8, RTF 2.09) 대비
  7배 빨라짐 — decode 자체는 GPU가 확실히 도움되지만 diarization/VAD는 20초 클립과
  동일하게 **GPU가 오히려 손해**임이 6분 전체 데이터로도 확정됨.

**병목 결론 (실측 확정)**: 현재 최선 조합(ASR=faster-whisper CUDA, 화자분리=sherpa
CPU, GPU는 diarization/VAD에는 끄는 것)의 합산 추정 RTF:

```
RTF ≈ 0.027(ASR, 실측) + 0.170(화자분리 CPU, 실측) + 0.004(VAD, 무시 가능) ≈ 0.20
```

10분(600초) 환산: **약 120초(2분)**. 기존 14분 대비 크게 개선됐으나 목표(60초,
RTF≤0.1)의 약 2배. 이 추정치는 두 실측값의 산술 합이며, 두 엔진을 실제로 하나의
파이프라인으로 합쳐서 끝까지 실행해본 결과는 아직 아니다(ASR과 화자분리를 순차가
아니라 병렬로 실행하면 wall time이 max(0.027, 0.170)≈0.17까지 줄 가능성 있음 —
미검증, 다음 조사 대상).

**정확도는 아직 미확인**: 위 속도 수치는 전부 faster-whisper `small` 모델 기준이며,
한국어 임상 전사 정확도(약명/용량/부정 표현 등)는 전혀 검증되지 않았다. 실제 녹음
내용은 볼 수도, 요청할 수도 없어(개인정보 규칙) `scripts/check_faster_whisper_
accuracy.py`(신규, `make check-faster-whisper-accuracy`)를 만들어 기존 합성
ground truth(sample_consultation.wav)로 검증하도록 했다 — 아직 사용자가 실행 전.

**버그 수정**: `scripts/compare_asr_engines.py`의 faster-whisper/SenseVoice
후보가 오디오 길이 계산에 `wave.open()`(WAV 전용)을 써서 실제 m4a 녹음에서
크래시함(`wave.Error: file does not start with RIFF id`) — ffprobe 기반
`_audio_duration_seconds()`/ffmpeg 기반 `_load_pcm_via_ffmpeg()`로 교체,
회귀 테스트 추가(`apps/api/tests/test_compare_asr_engines_audio_loading.py`,
합성 wav를 테스트 시점에 m4a로 transcode해 검증, 새 바이너리 fixture 커밋 없음).

**다음**: `make check-faster-whisper-accuracy`로 정확도 확인(속도만으로 채택 금지
원칙), 화자분리 자체의 GPU/경량화 대안 조사(PyTorch 기반 pyannote.audio 등 —
미확정, 공개 자료 기반 가설일 뿐 이 PC 실측 아님), ASR·화자분리 병렬 실행 검토.

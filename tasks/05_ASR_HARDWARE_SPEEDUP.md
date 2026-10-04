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

**`make check-faster-whisper-accuracy` 실측 결과 (small 모델) — 채택 불가**:

- 1/4 anchor pass. 통과한 1개(날짜 "시월")도 "시월드홉"이라는 깨진 단어 안의
  우연한 부분 문자열 일치로, 실질적으로는 0/4에 가깝다.
- anchor 점수보다 더 심각한 건 predicted 텍스트 자체다 — 단순히 부정확한 게
  아니라 거의 모든 구간이 의미 없는 한글 음절 나열로 무너졌다. 예:
  `오늘 혈압을 재보니 145에 92로 조금 높게 나왔습니다` →
  `오늘 혀가 풀채 보니 패스하시, 오에구시, 이보초금, 롯게나와 습니다`.
  "정확도가 조금 낮다" 수준이 아니라 환각(hallucination)에 가깝다.
- 결론: **faster-whisper `small`(244M, multilingual)은 이 용도(한국어 임상
  발화)에 채택 불가.** RTF 0.02~0.03이라는 속도만으로 판단했다면 완전히 잘못된
  선택을 했을 뻔했다 — "속도만으로 엔진을 결정하지 말라"는 원칙이 그대로
  적용된 사례.
- 다음 시도: **`large-v3`**(현재 기본 경로가 쓰는 것과 동일한 Whisper 가중치,
  CTranslate2 런타임만 다름 — 한국어 정확도는 large-v3 수준을 유지하면서도
  CTranslate2의 속도 이점이 어느 정도 남는지 확인 필요, 8GB VRAM에 fp16으로
  적재 가능할 것으로 예상되나 미확정):
  ```bash
  FASTER_WHISPER_MODEL=large-v3 make check-faster-whisper-accuracy
  FASTER_WHISPER_MODEL=large-v3 ENGINES=faster_whisper_cuda_fp16 make compare-asr-engines AUDIO=<6분 파일>
  ```

**`large-v3` 실측 결과 — 속도는 목표 달성, 그러나 새로운 안전 문제 발견**:

- 59.5초 합성 파일(정확도): RTF 0.056, 1/4 anchor pass(날짜만). `small`과 숫자는
  같지만 텍스트 품질은 전혀 다르다 — 환각이 아니라 읽을 수 있는 한국어 음성학적
  오류 수준(예: "재보니"→"채워니", "145에 92로"→"백사십 오에구십 이로"(숫자를
  글자로), "리시노프릴 오 밀리그램"→"리신 오프리오 밀크레믈").
- **가장 중요한 발견**: seg_005 부정 표현이 사라졌다 — 기대
  `"아스피린은 지금 시작하지 않습니다"` → 예측 `"아스피린은 지금 시작하기란
  습니다"`. **"않"이 완전히 소실**되어 중단/부정 의미가 사라졌다. 이는 날짜
  오류보다 임상적으로 훨씬 위험한 실패 유형이다(CLAUDE.md: "부정, 불확실성...
  구분한다").
- 비교: 현재 기본 엔진(sherpa-onnx, ko_only, 이전 실측)은 정확히 반대 패턴이었다
  — 부정 표현은 보존(`"아스은 지금 시작하지 않습니다"`, PASS)했지만 약명/용량/
  날짜는 실패했다. **두 엔진 모두 "1/4 pass"로 숫자는 같지만, 실패하는 항목이
  다르고 large-v3가 실패하는 항목(부정 표현)이 더 위험하다.** anchor 개수만
  보면 이 차이가 보이지 않는다.
- 6분 실제 녹음(속도): warm_decode_ms 29,393.3, **RTF 0.076** — ASR 단독으로는
  **처음으로 목표(≤0.1) 달성**. gpu_util 94%/100%(평균/최대, 완전 포화), VRAM
  5,213MB(8GB 중), cpu_util 13%대(GPU bound 확인).

## 종합 비교표 (실측 기반, 2026-10-04 기준)

| 후보 | 6분 실측 | 10분 환산(RTF 기반) | RTF | 정확도(anchor 1/4 공통, 실패 항목) | VRAM | 추가 비용 | 구현 난도 | 주요 위험 |
|---|---|---|---|---|---|---|---|---|
| 현재 기본(sherpa-onnx large-v3, CPU, ko_only) | 862.5s | ~1344s(22.4분) | 2.24 | 1/4 — **부정 표현 보존**, 약명/용량/날짜 실패 | - | 없음(이미 적용) | - | 너무 느림(14분 실측과 일치) |
| faster-whisper `small`, CUDA fp16 (ASR만) | 10.2s | ~16s | 0.027 | 1/4(거짓양성) — 거의 전체 환각 수준 붕괴 | 1.8GB | pip만 | 낮음 | **정확도로 채택 불가** |
| faster-whisper `large-v3`, CUDA fp16 (ASR만) | 29.4s | ~46s | **0.076** | 1/4 — **부정 표현 소실**(약명/용량은 small보다 개선) | 5.2GB | pip만 | 낮음 | 부정 표현 소실(안전 문제, 하류 검증 필수) |
| 화자분리(diarization), sherpa CPU (불변, 모든 후보 공통) | 65.2s | ~102s | 0.170 | 화자분리 자체 정확도는 별도 미검증 | - | 없음 | - | GPU로 가속 안 됨(6분 전체 실측으로 확정, 오히려 22% 느려짐) |
| **경로 A**: large-v3 CUDA(ASR) + sherpa CPU(화자분리), 순차 실행 | 29.4+65.2≈94.6s | ~148s(2.5분) | ~0.246 | 위 두 행 결합, 부정표현 소실 위험 이전 | ~5.2GB(순차) | pip만 | 중간(엔진 교체+기존 화자분리 유지) | 목표(60s) 미달이나 14분→2.5분(5.7배) |
| **경로 B**: 경로 A + ASR/화자분리 **병렬** 실행(GPU+CPU 동시) | 미실측 | ~100s 추정(max(29.4,65.2)≈65s 기준) | ~0.17 추정 | 동일 | 동일 | 중간~높음(파이프라인 재설계 필요) | **설계 가정일 뿐 실측 없음** |

*10분 환산은 각 행의 실측 RTF × 600초이며, "경로 B"만 실측이 아닌 설계 가정(순차→병렬 전환 시 wall time이 두 단계 중 더 긴 쪽에 근접한다는 일반적 가정)이다 — 공개 벤치마크가 아니라 이 PC의 실측값을 조합한 것이지만, 병렬 실행 자체는 아직 구현/실측되지 않았다.*

## 3가지 결론 (item 5)

**1. 현재 병목과 중복 계산 여부**: 처음엔 ASR 디코딩 연산량 자체(이중 디코딩 같은
중복 계산은 아니었음, Task 03에서 이미 제거됨)가 병목이었다. faster-whisper+CUDA로
이를 해결하자(RTF 2.24→0.076), **화자분리(diarization) 자체가 유일하게 남은
병목**으로 확정됐다 — RTF 0.17이고, GPU를 줘도 가속되지 않는다는 것을 6분 전체
데이터로 재확인했다(segmentation 단계가 sherpa-onnx API에 provider 설정 지점이
없음, 코드로 직접 확인).

**2. 현재 로컬 장비(RTX 4060 Ti)만으로 10분→60초 목표가 가능한가**: **ASR만
놓고 보면 이미 가능하다**(large-v3+CUDA, RTF 0.076 < 0.1, 6분 실측으로 확인).
그러나 화자분리를 더하면 순차 실행 시 RTF~0.25(10분 기준 ~148초)로 목표를
넘긴다. 병렬 실행(ASR=GPU, 화자분리=CPU, 리소스가 겹치지 않음)을 쓰면 이론상
RTF~0.17(~100초)까지 줄 가능성이 있으나 **아직 구현/실측되지 않은 가정**이다.
즉 현재 장비로 "거의 도달"은 가능해 보이지만, 60초를 확실히 지키려면 화자분리
자체의 재구현(실제 가속 확인 또는 더 가벼운 방식)이 추가로 필요하다 — 장비
교체가 아니라 **소프트웨어 설계 변경**이 관건이라는 뜻이다.

**3. 추천 경로 2개**:
   - **경로 A (낮은 리스크, 즉시 적용 가능)**: ASR 엔진을 faster-whisper
     large-v3(CUDA fp16)로 교체(이미 opt-in 플래그/도구 준비됨), 화자분리는
     현재 그대로(CPU) 유지. 14분→약 2.5분(RTF 0.246, 5.7배 개선). **단, 부정
     표현 소실이 확인됐으므로 structure_llm/clinical_enrichment 단계의 "근거
     없는 확정 금지" validator를 반드시 거쳐야 하고, 부정 표현이 포함된 약물
     중단/시작 지시는 자동 신뢰하지 말고 `needs_review`로 보내는 하류 안전장치가
     필수다.** 선택 기준: 지금 당장 체감 개선이 급하고, 하류 검증을 강화할
     여력이 있을 때.
   - **경로 B (목표 완전 달성 시도, 추가 개발 필요)**: 경로 A + ASR/화자분리
     병렬 실행 파이프라인 재설계(미실측) + 화자분리 자체 최적화(예: PyTorch
     기반 pyannote.audio로 교체 — CUDA 지원이 더 나을 것으로 보이는 공개 자료
     기반 가설일 뿐 이 PC 실측 아님). 60초 목표에 가장 근접하지만 구현 난도와
     검증 비용이 크고, 아직 아무것도 실측되지 않았다. 선택 기준: 60초를
     엄격한 제품 요구사항으로 지켜야 할 때.

   **공통 전제**: 두 경로 모두 정확도(특히 부정 표현 보존)를 하류에서 반드시
   재검증해야 하며, 속도 개선을 이유로 이 검증을 생략해서는 안 된다.

## 경로 B 병렬 실행 실측 결과 — 스레드 방식은 효과 없음 (가정 반증)

`make parallel-asr-diarization`(threading.Barrier로 동시 시작)을 6분 실제
파일로 실행한 결과, 위에서 "미실측, ~0.17 추정"이라고 적었던 가정이 **반증됐다**:

- 순차: 94,200ms (diarize 64,562ms + asr 29,638ms)
- 병렬(스레드): 94,668ms — **speedup 1.00x, 전혀 빨라지지 않음**
- overlap window는 65,024.8ms로 커 보였지만(두 스레드 모두 "시작된" 상태가
  전체 구간과 겹침), 이건 실제 동시 연산의 증거가 아니었다 — ASR 스레드의
  종료 시각(+94,668.4ms)이 diarize 종료 시각(+65,025.1ms) + ASR 단독
  소요시간(29,638.5ms) ≈ 94,663ms와 거의 정확히 일치한다. 즉 **diarization이
  GIL을 계속 쥐고 있어 ASR 스레드가 diarize가 끝날 때까지 거의 진행하지 못한
  것**으로 보인다.
- 스크립트 자체의 1차 판정 로직도 틀렸었다(overlap window 크기로 "병렬화
  유효"라고 잘못 출력함) — speedup 수치로만 판정하도록 수정함
  (`scripts/parallel_asr_diarization.py`).

**`make parallel-asr-diarization-mp`(별도 OS 프로세스, GIL 공유 없음)로
재시도 — 결과는 사용자 실행 대기 중, 아직 미실측.** GIL이 원인이었다면
프로세스 기반에서는 실제 speedup이 나와야 하고, 그래도 안 나오면 다른 자원
경쟁(디스크 I/O, CUDA 드라이버 초기화 등)을 봐야 한다.

**결론 2 수정**: "병렬 실행 시 RTF~0.17"이라는 이전 추정은 **스레드 기반으로는
틀렸음이 실측으로 확인됐다**. 경로 B의 실제 유효성은 별도 프로세스 결과가
나와야 확정된다 — 그 전까지는 경로 A(순차, RTF 0.246, 10분→~148초)가 유일한
실측 기반 수치다.

## 프로세스 기반 병렬 실행 실측 결과 — GIL 가설 확인, 유효함

`make parallel-asr-diarization-mp`(별도 OS 프로세스, GIL 공유 없음) 6분 실제
파일 결과:

- 순차(단일 프로세스, 같은 run): 93,672ms (diarize 64,337ms + asr 29,335ms,
  RTF 0.243)
- 병렬(별도 프로세스): **65,054ms (RTF 0.169)** — speedup **1.44x**
- diarize는 +65,054ms에 종료(단독 64,337ms와 거의 동일, 오버헤드 1.1%),
  asr는 +29,521.5ms에 종료(단독 29,335ms와 거의 동일, 오버헤드 0.6%) — **두
  작업이 실제로 각자 거의 최대 속도로 동시에 돌았다.** GIL이 스레드 버전의
  원인이었다는 가설이 그대로 확인됐다.
- 전체 wall time은 이제 더 느린 쪽(diarization, 65s)이 전부 결정한다 — ASR은
  29.5초에 이미 끝나버려서 더는 전체 시간에 영향을 주지 않는다.

**10분 환산: RTF 0.169 × 600 ≈ 101초(1.7분).** 기존 14분 대비 8.3배 개선,
목표(60초)의 1.7배로 좁혀졌다. **단, 병렬화만으로는 60초를 완전히 달성하지
못한다** — ASR은 이미 병목이 아니고(29.5s), diarization 자체(65s, RTF 0.169)
가 유일한 critical path이기 때문이다. 60초를 엄격히 달성하려면 diarization
자체를 RTF 0.1 밑으로 더 줄여야 한다(병렬화와는 별개의 추가 작업 — 예: 더
가벼운 segmentation 모델, 또는 PyTorch 기반 pyannote.audio로 교체해 실제 GPU
가속을 받는 것 — 여전히 공개 자료 기반 가설, 이 PC 실측 아님).

**경로 B 최종 상태**: 더 이상 가정이 아니다 — 프로세스 기반 병렬 실행은
**실측으로 확인된 유효한 개선**이다(스레드는 효과 없음, 프로세스는 1.44x).
다만 구현하려면 실험 스크립트 수준을 넘어 실제 파이프라인에 worker process
관리를 추가해야 한다(`app/dependencies.py`의 provider 캐싱과 함께 설계 필요,
에러 전파·타임아웃·IPC 등 포함 — 아직 구현되지 않음, 별도 엔지니어링 작업).

### 최종 추천 (3단계로 재정리)

| 단계 | 구성 | 10분 환산 | 구현 난도 | 비고 |
|---|---|---|---|---|
| 경로 A | ASR만 large-v3 CUDA로 교체, 순차 | ~148초 | 낮음(opt-in 플래그, 이미 준비됨) | 즉시 적용 가능 |
| 경로 B | 경로 A + diarization/ASR 별도 프로세스 병렬 실행 | **~101초(실측 확인)** | 중간(worker process 아키텍처 신규 설계) | 60초 목표엔 아직 못 미침 |
| 경로 C | 경로 B + diarization 자체 가속/경량화 | 미실측, RTF<0.1 달성 시 60초 이내 가능 | 높음(diarization 엔진 교체 또는 재구현) | 가설 단계, 미착수 |

선택 기준: 지금 당장 체감 개선이 급하면 A. 60초에 최대한 가깝게(1.7분) 가면서
중간 수준 개발로 끝내고 싶으면 B(실측으로 유효성 확인됨). 60초를 엄격한
제품 요구사항으로 지켜야 하면 C까지 가야 하고, 그 전에 diarization 가속
가능성을 먼저 실측으로 확인해야 한다. **모든 단계에서 부정 표현 보존 문제는
별개로 하류 검증이 필요하다(이미 확인됨).**

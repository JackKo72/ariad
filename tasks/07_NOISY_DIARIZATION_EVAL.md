# Task 07: 소음 환경 화자분리 평가셋 + DER 측정

## 배경 (사용자 요청, 2026-10-09)

외래·병동회진 5~10분 녹음, 단일 채널, 화자 최대 4명. 소음은 옆방 음악,
공사 소리, **옆 환자 회진 겹침**(보통 우리 회진이 더 큼). "이 heterogeneous한
환경에서도 의사 발화와 환자/보호자 발화가 분리되느냐"를 엔진·전처리 설정별로
**정답을 아는 데이터**로 비교할 수 있어야 한다. 화자 수만 세던
`compare_diarization_engines.py`로는 판단 불가.

## Outcome

`make noisy-diarization-set && make eval-diarization-der ENGINES=...` 한 번으로
조건(clean/음악/공사/옆 회진 × SNR) × 엔진 × 전처리(none/light_denoise)별
DER·miss·FA·confusion·**배경 누출률**을 표로 본다.

## In scope

- `scripts/compare_diarization_engines.py`: Sortformer v2 streaming 후보
  (`sortformer_cuda` ~10 s 지연, `sortformer_cuda_low` ~1 s), 엔진별
  `speakers_detected`, 엔진별 `segments`(DER 계산용, 콘솔 출력에서는 제외).
- `app/eval/diarization_metrics.py`: NIST 정의 frame DER(최적 화자 매핑,
  collar, overlap 포함) + background leakage.
- `app/eval/noise_mix.py`: 발화 구간 기준 정확한 SNR 혼합, 클리핑 방지.
- `scripts/generate_noisy_diarization_set.py`: 기존 합성 fixture만으로 평가셋
  생성(외부 다운로드 없음). 정답은 JSON + RTTM(타 도구 호환).
- `scripts/eval_diarization_der.py`: 평가 실행 + `der_results.json`.

## Out of scope

- 실제 앱 파이프라인(`SherpaOnnxASRProvider`) 설정 변경 — 측정 전에는 안 바꾼다.
- "배경 의심 화자" 자동 표시, 역할 확인 UI의 "배경/무관" 선택지 — 측정 결과로
  필요성이 확인되면 별도 task.
- streaming 업로드 구조(별도 채팅/task).
- ASR CER·의학용어 정확도의 소음 조건별 측정 — 같은 평가셋으로 다음 단계에서
  가능(정답 transcript는 원본 fixture에 이미 있음).

## 평가셋 정의

| 조건 | 생성 방법 | 정답 |
|---|---|---|
| clean | 원본 fixture(기본 `sample_consultation`) | 원본 화자 구간 |
| music_snrN | 합성 화음+베이스+비브라토 멜로디(가사 없음) | 원본 구간 |
| construction_snrN | 불규칙 망치 충격음 + 간헐적 드릴 | 원본 구간 |
| neighbour_snrN | 두 번째 합성 대화(기본 `vital_signs_dictation`)를 1.12배 pitch-shift, 2 s 오프셋 | 원본 구간 + `BG_*` 배경 화자(`background: true`) |

- SNR = 우리 발화 구간 전력 / 간섭 전력(옆 회진은 그 발화 구간 전력). 0/5/10 dB 기본.
  SNR 5 = 우리 회진이 옆 회진보다 약 1.8배(진폭) 큼.
- 실제 음악/공사 녹음(CC0 등, 환자 음성 없는 것)은 `NOISE_MUSIC=`,
  `NOISE_CONSTRUCTION=`으로 교체 가능. 실제 음악은 보컬이 있는 경우가 많아
  합성 음악보다 어렵다.

## 지표

- DER = (miss + FA + confusion) / 정답 발화 시간, collar 0.25 s.
- **bg_leak** = 옆 회진만 말하는 시간 중, 우리 의사·환자로 매핑된 라벨이 붙은
  비율. 임상적으로 가장 위험한 실패(남의 말이 우리 환자 말로 전사됨)를 직접 잰다.
  옆 회진을 아예 못 잡은 경우(miss)는 누출이 아니다.

## Acceptance criteria

- oracle 엔진은 모든 조건에서 DER 0, 전부 한 클러스터로 묶는 엔진은 옆 회진
  누출률 100% (`test_eval_diarization_der.py`).
- 평가셋 정답 파일에 전사 텍스트가 없다. 콘솔에 화자 라벨·전사 출력 없음.
- 생성물은 gitignore된 `data/` 아래에만 쓴다.

## Tests

- Unit: `test_diarization_metrics.py`(11), `test_noise_mix.py`(8)
- Integration(스크립트 end-to-end, 가짜 엔진): `test_eval_diarization_der.py`(2)

## 실측 (이 샌드박스, CPU, sherpa_cpu = 현재 앱 설정)

`make noisy-diarization-set` 기본값(sample_consultation 59.5 s, 2인) + sherpa
segmentation-3.0/eres2net(앱과 같은 `build_diarizer`, num_speakers=0). Whisper는
화자분리에 쓰이지 않아 이 측정에는 불필요. 2026-10-09.

| 조건 | prep | DER% | miss% | FA% | conf% | bg_leak% | spk ref/hyp |
|---|---|---:|---:|---:|---:|---:|---:|
| clean | none | 21.0 | 0.6 | 0.0 | 20.4 | - | 2/1 |
| clean | light_denoise | 20.5 | 0.0 | 0.0 | 20.5 | - | 2/1 |
| music 0/5/10 dB | none | 20.7~20.9 | ≤0.5 | 0.0 | 20.5 | - | 2/1 |
| construction 0/5/10 dB | none | 21.5~21.9 | 0.0 | 1.0~1.4 | 20.5 | - | 2/1 |
| construction 10 dB | light_denoise | 16.0 | 0.0 | 0.4 | 15.6 | - | 2/2 |
| neighbour 0 dB | none / light | 49.5 / 38.2 | 2.0 / 0.1 | 1.5 / 1.3 | 46.0 / 36.9 | 30.3 / 54.5 | 4/6, 4/6 |
| neighbour 5 dB | none / light | 41.0 / 48.7 | 4.2 / 6.7 | 1.0 / 0.9 | 35.8 / 41.2 | 45.5 / 30.3 | 4/6, 4/11 |
| neighbour 10 dB | none / light | 42.4 / 45.3 | 22.9 / 25.4 | 0.4 / 0.5 | 19.0 / 19.4 | 69.7 / 69.7 | 4/5, 4/6 |

RTF 0.13~0.28 (샌드박스 CPU, 사용자 하드웨어 0.17보다 느림).

해석:
1. **clean에서 이미 2명을 1명으로 합친다**(DER 21%, 전부 confusion). README의
   "같은 TTS 보이스 fixture에서 화자분리 실패"를 수치로 재현한 것. 이 baseline
   실패가 음악·공사 조건의 차이를 가린다 — 음악/공사가 "괜찮다"는 결론은 이
   데이터로 내릴 수 없다(목소리가 다른 fixture 필요).
2. **옆 회진은 명확히 문제**: DER 38~50%, 옆 회진 발화의 30~70%가 우리 화자
   라벨로 들어간다. 특히 옆 회진이 **조용할수록(10 dB) 누출이 더 크다**(69.7%) —
   별도 클러스터로 떨어지지 못하고 우리 화자에 흡수된다. "우리가 더 크다"는
   사실만으로는 현재 클러스터링이 안전해지지 않는다.
3. light_denoise는 일관된 이득이 없다(조건에 따라 좋아지기도 나빠지기도 함).
   음성끼리 겹치는 문제는 denoise로 풀리지 않는다는 예상과 일치.
4. 옆 회진 화자는 원본과 같은 espeak 음성의 pitch-shift라 실제보다 구분이 어렵다
   — 누출률 절대값은 비관적일 가능성이 크다. 다만 방향(조용한 배경 화자가 흡수됨)은
   num_speakers 고정 시 더 악화될 구조라, "화자 수 상한만 두고 고정하지 않기"
   권고를 유지한다.

## 남은 위험

- 기본 fixture는 같은 espeak-ng 음성의 pitch 차이로만 화자를 구분한다. 실제
  목소리보다 비관적인 DER이 나온다. 절대값이 아니라 **엔진·설정 간 상대 비교**용.
- 합성 소음은 실제 병원 소음의 근사다. 결론 전에 실제 소음 녹음으로 교체해
  재측정 권장.
- 1분짜리 2인 fixture 기준이다. 5~10분, 3~4인 합성 대화 fixture가 추가로 필요
  (TTS로 만들되 화자별 다른 음성 엔진 권장).
- Sortformer는 영어 위주 학습 모델 — 한국어 성능은 이 평가셋으로 직접 재야 한다.

# Task 08: 실제 목소리 역할극 녹음의 반자동 정답지

## 배경 (사용자 요청, 2026-10-09)

task 07 평가셋은 같은 TTS 음성이라 DER 절대값이 비관적이었다. 사용자가 실제
목소리로 만든 **가상(역할극) 녹음**을 제공: ICU 보호자 상태설명(5분 31초),
ER 뇌졸중 환자 exam + 동료 디렉션 + 소음 + 환자·보호자 설명(압축 업로드 예정),
그 외 몇 개 더. 이 녹음들로 정답지를 만들어 DER을 재고, 이후 화자분리 튜닝/
적응에 쓰고자 함.

## Outcome

녹음 → 초안(`make draft-annotation`) → Audacity에서 수정 → `make
labels-to-reference` → `make eval-diarization-der SET_DIR=data/annotations`로
녹음 여러 개를 한 번에 채점.

## In scope

- `scripts/draft_reference_annotation.py`: Audacity 라벨 초안. Whisper 모델이
  있으면 앱 ASR 텍스트까지, 없으면 화자분리 구간만.
- `scripts/labels_to_reference.py`: 라벨 → `<stem>.ref.json`. 화자
  `DOC/DOC2/PT/GUARD/STAFF/BGn`, 발화 유형 `exam/order/explain/other`.
  오류가 하나라도 있으면 줄 번호와 함께 전부 보고하고 아무것도 쓰지 않는다.
- `scripts/eval_diarization_der.py`: manifest 없는 폴더는 `<stem>.ref.json` +
  같은 이름 오디오 쌍을 자동 탐색.
- `compare_diarization_engines.py`: `sherpa_cpu_2spk/3spk/4spk` 후보.

## Out of scope

- 화자분리 파라미터 튜닝, segmentation 모델 fine-tuning — 정답지가 쌓인 뒤
  별도 task (아래 "다음 단계").
- 발화 유형(`discourse`)을 쓰는 LLM 구조화 채점 — 정답 필드만 먼저 확보.

## 라벨 규칙

`start<TAB>end<TAB>SPEAKER|TYPE|text`

| SPEAKER | 의미 |
|---|---|
| DOC, DOC2.. | 의사 (녹음 주체 = DOC) |
| PT | 환자 |
| GUARD, GUARD2.. | 보호자 |
| STAFF, STAFF2.. | 이 진료에 참여한 간호사·직원 |
| BG1, BG2.. | 이 진료와 무관한 발화(옆 침상, 방송, 지나가는 사람). 목소리마다 다른 번호 |

- 겹친 발화는 구간을 겹쳐서 표시한다.
- 텍스트는 의학용어·숫자 구간만 고쳐도 된다(화자분리 채점에는 텍스트 불필요).

## 사전 측정 (ICU 녹음, 정답 없음, sherpa_cpu)

- 자동 모드에서 9개 화자가 나왔다. 그중 1명이 245초(93%)이고 나머지 8명은 1~6초 조각이다.
- 2명 고정 시 252초 / 13초, 3명 고정 시에도 2명.
- 보호자 발화가 실제로 13초인지 흡수된 것인지는 정답지로 판정.

## 개인정보

- 녹음, 초안, 정답지는 gitignore된 `data/annotations/`에만 둔다. 커밋 금지.
- 역할극이라도 목소리는 실제 사람의 생체정보다. 녹음 참여자에게 평가·모델
  학습 용도 사용 동의를 받는다. 실제 환자 녹음은 IRB 없이 쓰지 않는다.

## Tests

- `test_reference_annotation.py`(3): 정상 라벨 변환, 모든 오류 줄 보고,
  폴더 자동 탐색으로 oracle DER 0.

## 다음 단계 (정답지가 쌓인 뒤)

1. 파라미터 튜닝: clustering threshold, min_duration_on/off,
   화자 수 정책을 grid search. 녹음 단위 leave-one-out으로 과적합 확인.
2. 데이터 증강: 정답지가 있는 녹음을 `CLEAN=`/`CLEAN_GT=`로 넣어 소음 조건을
   늘린다. 분할은 반드시 녹음 단위로 해야 한다(같은 녹음의 소음 버전이 train과
   test에 동시에 들어가면 안 됨).
3. pyannote segmentation-3.0 fine-tuning 후 sherpa용 ONNX로 내보내기. 수
   시간 분량 정답지와 GPU가 필요하다.

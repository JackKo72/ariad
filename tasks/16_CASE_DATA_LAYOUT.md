# Task 16: 녹음 케이스 폴더와 EMR 참고 자료

## 범위 (사용자 결정, 2026-10-12)

- EMR은 **정답지 개선 참고 자료**와 **녹음 시점 메타데이터**로만 쓴다.
- 차트 맥락 입력(EMR을 LLM에 넣기)은 이번 단계에 없다. 앱·평가·LLM 어느 것도 `*.emr.txt`를 읽지 않는다.
- 녹음마다 가상의 환자 매칭 번호를 붙인다(`er_3023432.wma` ↔ `er_3023432.*`).

## 구현

- `apps/api/data/cases/<case>/`(gitignore): 원본 녹음, `.opus`, `.answer.txt`, `.transcript.json`,
  `.emr.txt`, `.meta.json`, 평가 출력. 사용법은 `docs/CASE_DATA.md`.
- `scripts/cases.py`(공용):
  - 경로와 정답지 찾기(`gold_case`로 기존 정답지를 계속 쓸 수 있음)
  - meta 검증
  - 개인정보 패턴 검사(줄 번호만 보고)
- `make check-cases [CASE=]`: 케이스마다 파일 유무, 오디오 길이, segment 수, meta(상대 녹음 시점
  포함), 정답지, 개인정보 의심 줄 번호를 보여 준다. 본문은 출력하지 않아서 채팅에 붙여 넣어도 된다.
- `make prepare-case-audio CASE=`: 원본(wma 등, 앱 업로드 검사는 WMA를 받지 않음)을 모노 16 kHz
  24 kbps opus로 바꾼다. 원본은 그대로 둔다.
- `make migrate-case OLD= NEW= [FROM=]`: 기존 `sim_*` 파일을 케이스 폴더로 옮기고 이름을 바꾼다.
  `gold_case`가 들어간 meta.json도 만든다. 덮어쓰지 않는다.
- `CASE=` 단축:
  - `make eval-structure`와 `make diagnose-structure`가 폴더에서 transcript, gold, frame을 찾는다.
  - 평가 출력 이름은 케이스 번호로 쓴다.
- `check-vocab-leakage`가 케이스 폴더의 eval 전사도 확인한다.

## 의도적으로 하지 않은 것

- EMR 본문을 읽는 코드는 없다(점검 스크립트의 개인정보 패턴 검사만 예외).
- 사람 이름 자동 탐지는 하지 않는다. 직접 확인해야 한다.
- 기존 정답지 파일 이름(sim_*)은 바꾸지 않았다. 새 번호는 meta의 `gold_case`로 연결한다.

## Tests

- `test_cases.py`(+5):
  - 개인정보 패턴을 줄 번호로 잡는다(혈압 120/80, 자기 케이스 번호는 제외)
  - meta 검증
  - CASE= 단축과 gold_case 연결
  - migrate가 이동·이름 변경·meta 생성을 하고 다른 케이스는 건드리지 않는다
  - check-cases가 본문을 출력하지 않는다
- 기존 ICU 녹음 복사본으로 이동 → opus 변환(5분 30초, 1.0 MB) → 점검 → 평가 → 진단 → 누출 검사를
  한 번에 확인했다.

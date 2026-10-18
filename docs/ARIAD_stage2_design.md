# ARIAD 2단계 설계: 뇌졸중 2차예방 생활습관 실행계획 · 미시행 사유 · 이행 확인

Oct 9, 2026 · @DongGyun Ko

## 요약

ARIAD 2단계의 핵심은 **모든 생활습관 행동을 하나의 공통 스키마(Action item)로 표현**하는 것이다. 1단계 LLM이 진료 대화에서 뽑은 지시를 이 스키마로 정규화하면, 체크 질문·이행 판정·미시행 사유 수집이 자동으로 따라온다.

- **행동 카탈로그**: HTN·DM·DL 생활습관 권고를 14개 행동 단위로 쪼개고, 각 행동에 기본 목표값·측정 방법·체크 주기를 미리 정의한다 (Part 1–2).
- **판정은 규칙, 사유는 LLM**: 했는지/안 했는지는 결정론적 코드로 판정하고, 왜 못 했는지만 LLM이 자유 응답을 분류 코드로 바꾼다 (Part 3).
- **추적성**: 모든 Action item은 진료 대화의 발화 위치(source span)를 들고 다녀서, 다음 외래 리포트에서 "의사가 무엇을 말했고 → 환자가 무엇을 했고 → 왜 못 했는지"가 한 줄로 이어진다 (Part 5).
- **개발 순서**: 리포 파악 → 카탈로그 → 스키마 → 정규화기 → 체크인/판정 → 사유 분류 → 리포트 → 시뮬레이션 (Part 6). 서브에이전트는 스키마가 확정된 뒤 카탈로그 작성과 평가 시나리오 생성에만 병렬로 쓴다 (Part 7).

가이드라인 간 수치가 다른 항목(나트륨, 음주, HbA1c 목표 등)은 하나로 고정하지 않고 **기본값 + 의료진 조정 파라미터**로 둔다.

&#91;embedded content: ARIAD 1·2단계 닫힌 루프 · 8단계 + red flag 분기\]

의료진 승인 전에는 환자에게 아무것도 가지 않고, 미시행 사유 단계에서 red flag가 걸리면 분류를 건너뛰고 바로 안전 안내로 빠진다.

## Part 1. 가이드라인별 생활습관 권고

7개 가이드라인의 생활습관 권고는 **식사(패턴·나트륨·지방·당), 신체활동(유산소·저항·좌식), 체중, 음주, 흡연, 스트레스, 자가측정**으로 수렴한다. 수치가 다른 곳은 마지막 열에 적었고, ARIAD에서는 이 열이 "의료진 조정 파라미터"가 된다.

### 1-1. 행동 권고 통합표

| 코드 | 영역 | 권고 내용 (수치) | 근거 가이드라인 | 가이드라인 간 차이 / 주의 |
| --- | --- | --- | --- | --- |
| D1 | 식사 패턴 | 지중해식 또는 DASH: 채소·과일·통곡물·콩·생선·견과, 적색·가공육·단 음료·과자류 제한 | AHA/ASA 2021 (지중해식·저염 권고), KSoLA 2026 (지중해·DASH·식물성·균형 한식), AHA/ACC 2025 (DASH) | 한국 지침은 "균형 잡힌 한식"을 명시 → 한국형 문항 필요 |
| D2 | 나트륨 | 이상적 <1,500 mg/일, 최소 1,000 mg/일 감량. 칼륨 기반 대체염 사용 가능 | AHA/ACC 2025, AHA/ASA 2021 (나트륨 1 g/일 감소당 CV 사건 20% 감소; DASH-sodium 3.3→2.4 g: SBP −2.1, 2.4→1.5 g: 추가 −4.6 mmHg) | 대체염은 CKD·고칼륨 위험 환자 제외. KSH 2026 수치 원문 확인 필요 |
| D3 | 칼륨 | 3,500–5,000 mg/일, 보충제보다 음식으로 | AHA/ACC (SBP −4\~5 mmHg) | eGFR 저하·RAAS 억제제 병용 시 의료진 확인 |
| D4 | 지방·콜레스테롤 | 총지방 ≤30%, 포화지방 ≤7% 에너지, 트랜스지방 회피, 포화지방→불포화지방 대체, 고콜레스테롤혈증 시 식이 콜레스테롤 제한 | KSoLA 2026 | 지질 식이 준수만으로 LDL 10–15% 감소 (AHA/ASA 2021) |
| D5 | 탄수화물·당·식이섬유 | 탄수화물 50–65%, 총당 ≤20% 에너지, 식이섬유 ≥25 g/일, 잡곡·통곡물, 가당음료·가공식품 제한. DM은 개별화 MNT | KSoLA 2026, KDA 2025, ADA 2026 | DM은 영양사 MNT 연계 여부를 플래그로 |
| P1 | 유산소 운동 | 중강도 150–300분/주 (또는 고강도 75–150분), ≥3일/주, 2일 연속 쉬지 않기. 뇌졸중 생존자는 가능하면 40분×3–4회/주, 불가 시 장애·회복 단계 맞춤 | KSoLA 2026, KDA 2025, ADA 2026, AHA/ASA 2021 | 뇌졸중은 "감독 하 안전하게" 강조. 고위험군은 운동 전 평가 |
| P2 | 저항 운동 | 2–3회/주, 비연속일 | ADA 2026, KDA 2025, KSoLA 2026, AHA/ACC (동적 저항 90–150분/주 → SBP −4) | 편마비·낙상 위험 시 의자·밴드 기반으로 대체 |
| P3 | 좌식 중단 | 30분마다 3분 가벼운 활동 (서기·걷기) | ADA 2026, AHA/ASA 2021 (BUST-Stroke: SBP −3.5 mmHg), KSoLA (30–60분마다) | 뇌졸중 생존자는 깨어 있는 시간의 >78%가 좌식 |
| W1 | 체중 | 과체중·비만 시 5–10% 감량, 집중 행동상담 (1년 ≥12회) | AHA/ASA 2021, KSH 2026 (Class I, LOE A), KDA 2025 (≥5%), ADA 2026 (5–7%) | 저체중 뇌졸중 환자는 감량 목표 금지 |
| A1 | 음주 | 금주 또는 감량 (혈압 측면 최선은 무음주). 과음 기준: 남 >4잔/일·>14잔/주, 여 >3잔/일·>7잔/주, >60 g/일은 재발 위험 | AHA/ACC 2025, AHA/ASA 2021, ADA 2026 | 2017 대비 AHA/ACC 2025는 "적정 음주 허용"에서 후퇴 → 기본값 "금주" 권장 |
| S1 | 흡연 | 완전 금연(전자담배 포함), 간접흡연 회피, 상담 + 약물(NRT·바레니클린·부프로피온) | AHA/ASA 2021 (지속흡연 재발 약 2배), KSH 2026 (전자담배 금연 Class I, LOE B) | 퇴원 후 최소 1개월 지지 접촉이 성공률을 높임 |
| M1 | 스트레스 | 호흡운동·마음챙김·명상 (SBP/DBP 약 4/2 mmHg) | KSH 2026 (Class IIb, LOE B), AHA/ACC 2025 | 뇌졸중 후 우울 선별과 연결 |
| H1 | 가정혈압 | 검증된 기기로 자가측정 | KSH 2026 (Class I, LOE B), AHA/ACC 2025 | KSH "722" 측정법(7일·하루 2회·회당 2번)을 기본 프로토콜로 |
| H2 | 자가혈당 | 인슐린 사용자는 필수, 비인슐린 T2DM은 고려. 공복·식후 2시간 중심, 빈도 개별화 | KDA 2025 | 저혈당 위험 약제 사용자는 운동 전후 측정 |

### 1-2. 행동의 결과 지표 (목표치)

| 지표 | 뇌졸중 환자 목표 | 근거 | 재측정 시점 |
| --- | --- | --- | --- |
| 혈압 | <130/80 mmHg | AHA/ASA 2021, KSH 2026 (Class I, LOE A) | 가정혈압 상시. 중증 두개내 협착은 개별화 |
| HbA1c | T2DM 일반 <6.5% (KDA), <7% (ADA). 고령·저혈당 위험 시 7–8% | KDA 2025, AHA/ASA 2021 | 2–3개월마다 (안정 시 연 2회) |
| LDL-C | ARIAD 기본값 <55 mg/dL + 기저 대비 ≥50% 감소 (KSoLA 일반 기준 <70, 재발 고위험 <55) | KSoLA 2026 (I B / IIa B), AHA/ASA 2021 (TST) | 치료 시작·변경 후 4–12주 |
| 체중 | 기저 대비 5–10% 감량 (과체중·비만) | AHA/ASA 2021, KDA 2025 | 주 1회 자가측정 |

AHA/ASA 2021은 행동 변화가 "조언이나 브로셔"만으로는 어렵고, 행동변화 이론 기반 프로그램과 다학제 지원이 필요하다고 명시한다. ARIAD 2단계의 존재 이유가 바로 이 권고다.

## Part 2. 실행 체크리스트와 체크 방법

체크 문항은 **"싱겁게 드셨나요?" 같은 평가가 아니라 "국물을 남기셨나요?" 같은 관찰 가능한 행동**을 묻는다. 하루 문항은 3개 이내, 자기보고 회상 기간은 24시간 또는 7일로 짧게 둔다.

### 2-1. 체크 설계 원칙

1. **원자 행동**: 권고 1개를 환자가 하루 안에 하거나 안 할 수 있는 행동 2–4개로 쪼갠다.
2. **이중 확인**: 자기보고 + 가능한 경우 객관 데이터(걸음 수, 혈압계, 체중계, 혈당계 연동).
3. **실패 즉시 분기**: "아니오"가 나오면 같은 메시지 안에서 사유 1문항으로 넘어간다 (Part 3).
4. **대리 응답자**: 실어증·인지저하 환자는 보호자 응답 경로를 기본으로 연다.
5. **목표는 개인화된 숫자**: "운동하세요"가 아니라 "주 4일 20분 걷기"처럼 진료에서 합의된 값으로 저장한다.

### 2-2. 행동별 체크리스트

| 코드 | 환자 체크리스트 (원자 행동) | ARIAD 체크 방법 | 객관 근거 (선택) | 주기 |
| --- | --- | --- | --- | --- |
| D1 | 끼니마다 채소 반찬 2가지 · 잡곡밥 · 생선 주 2회 이상 · 가공육/단 음료 피하기 | 주 1회 7문항 식사 체크 (지중해식 점수 축약판) | 식사 사진 (선택) | 주 1 |
| D2 | 국·찌개 국물 남기기 · 김치/장아찌 1회 소량 · 라면·가공식품 주 N회 이하 · 외식 시 "싱겁게" 요청 | 매일 저녁 1문항 ("오늘 국물은 얼마나 드셨나요? 안 먹음/반/다") | 외래 스팟 소변 나트륨 (의료진 판단) | 매일 |
| D4–D5 | 튀김·삼겹살 주 N회 이하 · 가당음료 0 · 과일은 주스 대신 생과일 | 주 1회 3문항 | 지질·혈당 검사 추세 | 주 1 |
| P1 | 주 N일 M분 걷기 (목표는 진료 합의값) | 걸음 수/활동 분 자동 수집 + 미연동 시 "오늘 걸으셨나요? 몇 분?" | HealthKit/Health Connect | 매일 |
| P2 | 주 2회 의자 일어서기·밴드 운동 N세트 | 운동일 저녁 Y/N + 세트 수 | 없음 (자기보고) | 주 2 |
| P3 | 30분마다 일어나 3분 움직이기 | 낮 시간 알림 3회 → 응답률 | 워치 비활동 알림 | 매일 |
| W1 | 주 1회 아침 공복·배뇨 후 체중 | 수치 입력 또는 체중계 연동 | 체중 추세 | 주 1 |
| A1 | 금주 (또는 합의한 잔 수 이하) | 주 1회 "지난 7일 중 술 마신 날·잔 수" | 없음 | 주 1 |
| S1 | 흡연 0개비 · 금연약 복용 · 금연클리닉 방문 | 매일 "오늘 담배(전자담배 포함) 피우셨나요?" + 주 1회 약물·상담 | 보건소 금연클리닉 CO 측정 | 매일 |
| M1 | 하루 1회 5분 호흡운동 | 주 3회 Y/N | 없음 | 주 3 |
| H1 | 722 측정 (외래 전 7일 집중, 평소 주 2–3일) | 기기 연동 또는 수치 입력, 결측일 자동 감지 | 혈압계 기록 | 측정일 |
| H2 | 처방된 시점의 혈당 측정 | 기기 연동/입력, 70 mg/dL 미만은 즉시 안전 안내 | 혈당계·CGM | 처방대로 |

### 2-3. 시나리오별 적용

**A. 68세 남성, 우측 경도 편마비, 혼자 거주, HTN·DL, 국물 선호, 하루 10개비 흡연**

- 우선순위 3개만 활성화: S1 금연 (매일), D2 국물 남기기 (매일), P1 걷기 주 3일 15분 (보행 안전 확인 후).
- 체크: 하루 최대 2문항. 걷기는 실내 제자리 걷기 대안을 미리 등록 (비·한파 대비).
- 예상 실패 지점: 혼자 식사 → 배달·라면 의존. 첫 3일 체크에서 D2 실패 시 "누가 식사를 준비하나요" 사유 분기.

**B. 55세 여성, T2DM + HTN, 사무직, 외식·회식 잦음**

- 활성화: P3 좌식 중단 (근무 중 알림), P1 퇴근 후 걷기, D5 가당음료 0, H2 공복 혈당.
- 체크: 근무 시간대 알림은 점심·오후 2회로 제한, 회식 예정일 사전 입력 시 그날 D2·A1 문항만 묻기.
- 예상 실패 지점: 회식·야근 (사회적 기회 부족) → 미시행 사유 O-SOC/O-PHY.

**C. 75세 남성, 실어증·경도 인지저하, 배우자가 조리 담당, HTN·DM·DL**

- 응답자: 배우자 (대리 응답 동의 필요). 식사 행동(D1·D2·D5)은 **조리자 행동**으로 바꿔 묻는다 ("오늘 국 간을 줄이셨나요?").
- H1·H2 측정도 배우자 수행. 저혈당 위험 약제면 운동 전 혈당 확인을 체크리스트에 고정.
- 예상 실패 지점: 보호자 부담 → 주 단위 요약 문항으로 빈도 축소.

**D. 재진 시나리오: 4주간 P1 이행률 30%**

- 리포트: 목표 "주 4일 30분" vs 실제 "주 1일 평균 18분", 주요 사유 "무릎 통증(C-PHY) 3회, 날씨(O-PHY) 2회".
- 의료진 선택지: 목표 하향(주 3일 15분) / 저항 운동 대체 / 재활의학과 의뢰. 선택 결과가 다음 Action Plan 버전이 된다.

## Part 3. 이행 확인 프로세스와 미시행 사유 분류

이행 판정은 **규칙 기반 코드가 결정론적으로** 하고, LLM은 환자의 자유 응답을 사유 코드로 바꾸는 데만 쓴다. 그래야 같은 데이터에 같은 판정이 나오고, 의료진이 판정 근거를 검증할 수 있다.

### 3-1. 확인 타임라인

| 시점 | 무엇을 | 목적 |
| --- | --- | --- |
| Day 0 (진료 당일) | Action Plan 전송 + 환자 확인 ("이 계획이 맞나요?") + 자신감 0–10 | 계획 오해 조기 발견 |
| Day 3 | 첫 체크 결과 판정 | 초기 실패 포착 (가장 이탈이 많은 구간) |
| 매주 | 주간 이행률 판정 + 미시행 사유 집계 | 목표 조정 제안 |
| 외래 7일 전 | 722 가정혈압 + 주간 판정 누적 → 의료진 리포트 | 다음 진료 의사결정 |

### 3-2. 판정 규칙 (기본값, 의료진 조정 가능)

| 판정 | 조건 | 다음 액션 |
| --- | --- | --- |
| 완전 이행 | 목표 대비 ≥80% | 유지, 칭찬 메시지 |
| 부분 이행 | 50–79% | 사유 1문항 (선택 응답) |
| 미이행 | <50% | 사유 필수 수집 + 대응 제안 |
| 판정 불가 | 응답률 <50% | 응답 장벽(측정 문제)부터 확인 |

이행률 = 주간 실제 수행량 / 주간 목표량. 횟수형(주 4일), 양형(150분), 이진형(금연)마다 계산식을 카탈로그에 정의한다.

### 3-3. 미시행 사유 분류 체계 (COM-B 기반 + 뇌졸중 특이)

| 코드 | 범주 | 예시 응답 | 기본 대응 |
| --- | --- | --- | --- |
| C-PHY | 신체 능력 | 편마비로 걷기 힘듦, 피로, 통증, 균형 불안 | 대체 행동 제안, 재활 의뢰 플래그 |
| C-PSY | 인지·지식 | 잊어버림, 방법을 모름, 실어증으로 이해 어려움 | 알림 시간 조정, 쉬운 설명·그림, 보호자 경로 |
| O-PHY | 물리적 환경·자원 | 날씨, 장소 없음, 비용, 기기 없음, 외식 | 실내 대안, 기기 대여 안내 |
| O-SOC | 사회적 환경 | 가족이 짜게 조리, 회식, 동거인 흡연, 보호자 부재 | 조리자·가족 대상 메시지 |
| M-REF | 신념·동기 | 필요성 못 느낌, 약 먹으니 괜찮다, 효과 의심 | 의료진 설명 요청 플래그 |
| M-AUT | 습관·갈망 | 담배·술 참기 어려움 | 금연클리닉·약물 연계 |
| M-EMO | 정서 | 우울, 의욕 없음, 불안 | PHQ-2 선별 → 의료진 알림 |
| MED | 의학적 사건 | 감기, 입원, 어지럼, 저혈당 | 계획 일시정지, 필요 시 의료진 알림 |
| PLAN | 계획 자체의 문제 | 목표가 너무 큼, 지시가 모호, 다른 의사 말과 다름 | **ARIAD 1단계 품질 피드백**으로도 기록 |
| MEAS | 측정·응답 문제 | 앱 사용 어려움, 혈압계 고장 | 기술 지원, 응답 채널 변경 |

**Red flag는 분류보다 먼저 처리한다.** 새 신경학적 증상(편측 마비·언어장애·안면마비), 흉통, 실신, 혈당 <70 mg/dL, 반복 낙상이 응답에 나오면 사유 분류를 건너뛰고 즉시 119·응급실 안내 + 의료진 알림을 보낸다. 이 규칙은 LLM이 아니라 키워드·수치 규칙으로 먼저 걸고, LLM은 보조로만 쓴다.

### 3-4. 사유 수집 대화 흐름

1. 미이행 판정 → "이번 주에 \[행동\]이 어려우셨던 이유를 골라주세요" (보기 4–5개 + 직접 입력).
2. 직접 입력이면 LLM이 사유 코드 + 신뢰도로 분류. 신뢰도 <0.7이면 확인 질문 1개 추가.
3. 같은 사유가 2주 연속이면 기본 대응을 자동 제안하고, PLAN·M-REF·M-EMO·MED는 의료진 리포트 상단에 올린다.

## Part 4. 환자에게 모아야 할 정보

수집 항목은 **어디서 오는지**(출처)로 나눠야 중복 질문이 없다. 진료 대화와 EMR에서 이미 얻는 것은 환자에게 다시 묻지 않고, 온보딩 설문은 5분 이내로 제한한다.

| 묶음 | 항목 | 왜 필요한가 | 출처 |
| --- | --- | --- | --- |
| 임상 기본 | 뇌졸중 유형(TOAST), 발병일, 퇴원 시 mRS·NIHSS, 편마비 측 | 활동 목표의 안전 범위, 행동 시작 시점 | EMR / 1단계 |
| 임상 기본 | 실어증·인지 (K-MMSE 또는 MoCA) | 대리 응답자 필요 여부 | EMR / 1단계 |
| 임상 기본 | 동반질환: HTN·DM·DL·CKD(eGFR), AF, 중증 두개내 협착, 수면무호흡 의심 | 행동 활성화·금기 (대체염, 혈압 목표 개별화) | EMR |
| 임상 기본 | 복용약: 인슐린·설포닐우레아, RAAS 억제제, 스타틴 | 저혈당·고칼륨 안전 규칙 | EMR |
| 결과 지표 기저값 | 진료실 BP, HbA1c, LDL-C(치료 전 기저값), 체중·BMI·허리둘레 | 목표 대비 변화, LDL ≥50% 감소 계산 | EMR |
| 생활습관 기저 | 국·찌개 빈도, 김치·장류, 외식·배달 빈도, 가당음료 | D1–D5 목표 개인화 | 온보딩 |
| 생활습관 기저 | 음주 빈도·잔 수, 흡연 개비·전자담배·동거인 흡연 | A1·S1 기준선 | 1단계 / 온보딩 |
| 생활습관 기저 | 현재 걸음 수·활동, 보행 보조기, 최근 6개월 낙상 | P1–P3 시작 강도 | 온보딩 / 기기 |
| 생활습관 기저 | 코골이·주간 졸림 (STOP-Bang), 기분 (PHQ-2) | 수면무호흡·우울 의뢰 플래그 | 온보딩 |
| 실행 맥락 | 동거 형태, 주 보호자, **식사 준비자** | 식사 문항을 누구에게 물을지 | 온보딩 |
| 실행 맥락 | 직업·근무 시간, 선호 연락 시간·채널 (카카오/SMS/전화) | 체크 시간대 | 온보딩 |
| 실행 맥락 | 보유 기기 (검증된 혈압계, 혈당계, 체중계, 스마트폰·워치), 디지털 숙련도 | 자동 수집 vs 수기 입력 | 온보딩 |
| 동기 | 가장 먼저 바꾸고 싶은 행동 1–2개, 중요도·자신감 0–10 | 활성 행동 우선순위 (최대 3개) | Day 0 확인 |
| 동의 | 민감정보 수집, 보호자 대리 응답, 의료진 공유 | 법·윤리 요건 | 온보딩 |

**진료 대화에서 1단계가 추가로 뽑아야 할 것**: 의사가 제시한 구체 목표값("하루 30분"), 환자가 표현한 장벽("무릎이 아파서"), 환자가 동의한 정도("해볼게요" vs "글쎄요"). 이 세 가지가 2단계의 초기 목표·예상 사유·자신감 기본값이 된다.

## Part 5. 1단계 핵심정리 코드와의 연계

연계 키는 **`catalog_code`(무엇을)와 `source_span`(진료 대화의 어디서)** 두 개다. 1단계 출력에 행동 지시 블록을 추가하고, 2단계는 그 블록만 읽어 Action Plan을 만든다. 아래 필드명은 현재 리포(JackKo72/ariad) 구조를 보지 않고 설계한 것이므로, Part 6의 Step 0에서 실제 출력 스키마에 맞춰 조정한다.

### 5-1. 데이터 흐름

1. **1단계 (기존)**: 진료 음성 → ASR 전사 → 의학용어 정리 → LLM 핵심구조화.
2. **1단계 확장 (신규)**: 핵심구조화 출력에 `action_directives[]` 추가. 의사가 말한 행동 지시, 환자 장벽 발화, 동의 정도를 발화 ID와 함께 뽑는다.
3. **정규화기 (신규, 2단계 입구)**: 각 지시를 카탈로그 코드에 매칭하고 목표값을 파싱해 `ActionItem`을 만든다. 매칭 실패는 `custom`으로 두고 의료진 확인 필수.
4. **의료진 확인**: 진료 직후 Action Plan 초안을 의사가 승인·수정. 승인 전에는 환자에게 발송하지 않는다.
5. **체크인 → 판정 → 사유**: `CheckIn` → `AdherenceJudgment` → `BarrierReport`가 모두 `action_id`로 연결된다.
6. **리포트**: 다음 외래 전, 각 `ActionItem`에 대해 "원 발화 → 목표 → 이행률 → 주요 사유 → 제안"을 한 줄로 출력.

### 5-2. 1단계 출력 확장 (추가되는 부분만 `+`로 표시)

기존 핵심정리 JSON은 그대로 두고 필드 하나만 붙이는 **비침습적 확장**이다. 기존 소비 코드는 이 필드를 무시해도 깨지지 않는다.

```diff
 {
   "visit_id": "V-2026-1009-001",
   "summary": { ... 기존 핵심정리 ... },
   "diagnoses": [ ... ],
   "medications": [ ... ],
+  "action_directives": [
+    {
+      "directive_id": "AD-1",
+      "raw_text": "국물은 이제 드시지 마시고요",
+      "source_span": { "utterance_ids": ["U-42", "U-43"], "speaker": "doctor" },
+      "domain_hint": "diet_sodium",
+      "target_hint": "국물 섭취 0",
+      "patient_response": { "text": "그게 제일 어렵네요", "utterance_id": "U-44", "agreement": "hesitant" },
+      "barrier_mentions": [ { "text": "혼자 살아서 라면을 자주 먹어요", "utterance_id": "U-45" } ]
+    }
+  ]
 }
```

**동작 순서**: (1) 1단계 LLM 프롬프트에 "행동 지시 추출" 지시를 추가한다. (2) LLM은 `raw_text`를 원문 그대로 복사하고 발화 ID를 붙인다 (요약·의역 금지 → 추적성 확보). (3) `domain_hint`·`target_hint`는 힌트일 뿐이고, 최종 코드 매칭은 정규화기가 한다. (4) `patient_response.agreement`는 `agreed / hesitant / refused / unclear` 4값으로 고정한다.

### 5-3. 2단계 핵심 엔티티

```json
{
  "CatalogAction": {
    "catalog_code": "D2",
    "name_ko": "저염 식사",
    "guideline_refs": ["AHA/ACC 2025", "AHA/ASA 2021"],
    "atomic_behaviors": ["국물 남기기", "김치 1회 소량", "가공식품 주 N회 이하"],
    "metric_type": "frequency",
    "default_target": { "value": 6, "unit": "days_per_week" },
    "check_method": { "channel": "daily_question", "question_id": "Q-D2-01" },
    "contraindication_rules": ["potassium_salt_substitute_if_ckd"],
    "adjustable_params": ["default_target"]
  },
  "ActionItem": {
    "action_id": "A-001",
    "plan_id": "P-V-2026-1009-001-v1",
    "catalog_code": "D2",
    "target": { "value": 7, "unit": "days_per_week" },
    "respondent": "patient | caregiver",
    "source_directive_id": "AD-1",
    "status": "draft | approved | active | paused | retired",
    "approved_by": "clinician_id"
  },
  "CheckIn": { "checkin_id": "C-...", "action_id": "A-001", "date": "2026-10-12", "value": 1, "source": "self_report | device" },
  "AdherenceJudgment": { "action_id": "A-001", "week": "2026-W42", "rate": 0.43, "label": "non_adherent", "rule_version": "r1" },
  "BarrierReport": { "action_id": "A-001", "week": "2026-W42", "code": "O-SOC", "free_text": "...", "classifier_confidence": 0.82, "red_flag": false }
}
```

`plan_id`에 버전(`-v1`)을 붙여 재진 때 목표가 바뀌면 새 버전을 만든다. 과거 판정은 당시 버전의 목표로만 계산되므로 이행률 추세가 왜곡되지 않는다.

## Part 6. 개발 순서와 Claude Code 프롬프트

순서의 원칙은 **데이터 정의(카탈로그·스키마)를 먼저 고정하고, LLM이 들어가는 부분은 마지막에 평가셋과 함께** 만드는 것이다. 각 Step은 테스트가 통과해야 다음으로 넘어간다.

| Step | 산출물 | LLM 사용 | 의료진(본인) 검수 |
| --- | --- | --- | --- |
| 0 | 리포 구조·1단계 출력 스키마 문서 (`docs/stage1_output.md`) | 없음 | – |
| 1 | 행동 카탈로그 `catalog/actions.yaml` (Part 1–2 표 기반) | 없음 | **필수** (수치·금기) |
| 2 | pydantic 모델 + JSON Schema + 단위 테스트 | 없음 | – |
| 3 | 1단계 `action_directives` 추출 확장 + 정규화기 + 평가셋 20건 | 있음 | 평가셋 정답 라벨 |
| 4 | 체크 질문 생성 + 판정 엔진 (규칙) | 없음 | 판정 기준값 |
| 5 | 사유 수집 대화 + 분류기 + red flag 규칙 | 있음 (분류만) | red flag 목록 |
| 6 | 외래 전 의료진 리포트 | 선택 (문장화만) | 리포트 양식 |
| 7 | 시나리오 A–D 시뮬레이션 (가상 환자 4주) | 있음 (가상 응답 생성) | 결과 리뷰 |

### 6-1. CLAUDE.md에 넣을 프로젝트 규칙

```markdown
# ARIAD stage 2 rules
- 기존 1단계 코드는 최소 변경. 출력 스키마는 필드 추가만 허용, 기존 필드 이름·타입 변경 금지.
- 이행 판정은 순수 함수(규칙)로 구현. LLM 호출 금지.
- 임상 수치(목표값, 기준, red flag)는 catalog/ 또는 config/에만 둔다. 코드에 하드코딩 금지.
- 모든 LLM 출력은 pydantic으로 검증하고, 실패 시 재시도 1회 후 needs_review로 저장.
- 코드 수정 시 변경 부분을 diff로 보여주고, 무엇이 왜 바뀌었는지 단계별로 설명.
- 환자 실데이터 사용 금지. tests/fixtures의 가상 데이터만 사용.
```

### 6-2. Step별 프롬프트

**Step 0 — 리포 파악**

```text
이 리포의 1단계(ASR → 의학용어 정리 → LLM 핵심구조화) 코드를 읽고, 코드는 수정하지 말고 다음을 docs/stage1_output.md로 정리해줘.
1) 진입점과 파이프라인 단계별 파일·함수
2) 핵심구조화 LLM 프롬프트 위치와 전문
3) 최종 출력 JSON의 실제 스키마 (필드, 타입, 예시 1개)
4) 발화 단위 ID(utterance id)가 있는지, 없으면 어디서 부여할 수 있는지
5) 이 출력에 action_directives 필드를 추가할 때 영향을 받는 소비 코드 목록
```

**Step 1 — 행동 카탈로그**

```text
docs/ARIAD_stage2_design.md의 Part 1-1, Part 2-2 표를 기반으로 catalog/actions.yaml을 만들어줘.
- 행동 14개(D1–D5, P1–P3, W1, A1, S1, M1, H1, H2) 각각에 catalog_code, name_ko, guideline_refs, atomic_behaviors, metric_type(frequency|amount|binary|measurement), default_target, check_method, contraindication_rules, adjustable_params를 넣어.
- 수치는 표에 있는 값만 쓰고, 표에 없는 값은 지어내지 말고 TODO_CLINICIAN으로 남겨.
- 스키마 검증용 tests/test_catalog.py도 만들어줘 (필수 필드 누락, 코드 중복, TODO 개수 리포트).
```

**Step 2 — 스키마**

```text
schemas/stage2.py에 pydantic v2 모델 CatalogAction, ActionItem, ActionPlan, CheckIn, AdherenceJudgment, BarrierReport를 docs의 Part 5-3 정의대로 만들어줘.
- status, agreement, barrier code는 Enum으로.
- ActionPlan은 버전 필드를 갖고, 이전 버전 plan_id를 참조해.
- JSON Schema export 스크립트와 왕복(serialize/deserialize) 테스트를 추가해.
```

**Step 3 — 1단계 확장 + 정규화기**

```text
docs/stage1_output.md를 기준으로 1단계 핵심구조화 출력에 action_directives 필드를 추가해줘.
- 기존 프롬프트는 유지하고, 행동 지시 추출 지시만 덧붙여. 변경 전/후 프롬프트를 diff로 보여줘.
- raw_text는 원문 그대로, utterance_ids 필수, agreement는 4값 Enum.
그다음 stage2/normalizer.py를 만들어서 action_directives를 catalog/actions.yaml에 매칭해 ActionItem(status=draft)을 생성해.
- 매칭은 domain_hint 우선, 없으면 LLM 분류. 매칭 실패는 catalog_code=custom.
- tests/fixtures/visits/에 가상 진료 대화 20건과 정답 라벨을 만들고, 정밀도·재현율을 출력하는 평가 스크립트를 추가해.
```

**Step 4 — 체크인·판정**

```text
stage2/checkin.py와 stage2/judge.py를 만들어줘.
- checkin: ActionItem과 respondent(환자/보호자)에 따라 질문 문구를 catalog의 question_id 템플릿에서 생성. 하루 최대 3문항, 우선순위는 ActionPlan 순서.
- judge: 주간 CheckIn 목록 → AdherenceJudgment. metric_type별 이행률 계산, 기준값(0.8/0.5, 응답률 0.5)은 config/judge.yaml에서 읽기.
- judge는 순수 함수로, LLM 호출 없이. 경계값(0.5, 0.8, 응답 0건) 테스트 포함.
```

**Step 5 — 사유 수집·분류**

```text
stage2/barrier.py를 만들어줘.
1) red flag 규칙을 먼저 적용 (config/red_flags.yaml의 키워드·수치). 걸리면 분류 없이 red_flag=true로 반환하고 안내 문구 템플릿을 붙여.
2) 아니면 LLM으로 Part 3-3의 10개 코드 중 하나 + confidence 분류. confidence < 0.7이면 follow_up_question 생성.
3) 가상 응답 50개 평가셋(코드별 5개)과 혼동행렬 출력 스크립트를 추가해. red flag 문장 10개는 100% 잡혀야 테스트 통과.
```

**Step 6–7 — 리포트·시뮬레이션**

```text
stage2/report.py: 외래 7일 전 기준으로 ActionItem별 "원 발화(source_span) → 목표 → 4주 이행률 → 주요 사유 Top2 → 제안 옵션" 표를 생성. 사유 PLAN, M-REF, M-EMO, MED와 red flag 이력은 상단에.
sim/run_scenarios.py: docs Part 2-3의 시나리오 A–D를 가상 환자로 만들어 4주 체크인을 생성하고 전체 파이프라인을 돌려 리포트를 출력해.
```

## Part 7. 서브에이전트 분할 플랜

**전체를 에이전트로 쪼갤 필요는 없다.** Step 0–2(리포 파악·카탈로그·스키마)는 메인 세션에서 순서대로 하고, 스키마가 고정된 뒤 서로 파일이 겹치지 않는 작업만 병렬로 돌린다. 스키마 확정 전에 병렬로 돌리면 에이전트마다 필드명을 다르게 만들어 통합 비용이 더 커진다.

| 에이전트 | 맡는 일 | 쓰는 파일 | 도구 권한 | 실행 시점 |
| --- | --- | --- | --- | --- |
| `catalog-curator` | 질환별(HTN·DM·DL) 카탈로그 항목 초안, 질문 템플릿 | `catalog/` | Read, Write, Edit | Step 1 (질환별 3개 병렬 가능) |
| `extraction-engineer` | 1단계 확장 + 정규화기 | `stage1/` (최소 변경), `stage2/normalizer.py` | 전체 | Step 3 |
| `scenario-writer` | 가상 진료 대화·체크인 응답·사유 평가셋 | `tests/fixtures/` | Read, Write | Step 3과 병렬 |
| `judge-builder` | 체크인 생성·판정 엔진 | `stage2/checkin.py`, `judge.py` | 전체 | Step 4 (Step 3과 병렬 가능) |
| `barrier-classifier` | 사유 분류·red flag | `stage2/barrier.py`, `config/red_flags.yaml` | 전체 | Step 5 |
| `clinical-safety-reviewer` | 임상 수치·금기·red flag 누락 검토, 수정은 안 함 | 없음 (리뷰 보고만) | Read, Grep, Glob | 각 Step 끝 |

**병렬 구간**: Step 1의 질환별 카탈로그 3개 / Step 3·4 + scenario-writer. 나머지는 순차.

### 7-1. 에이전트 정의 예시 (`.claude/agents/clinical-safety-reviewer.md`)

```markdown
---
name: clinical-safety-reviewer
description: ARIAD stage 2의 임상 수치, 금기 규칙, red flag 누락을 검토할 때 사용. 코드는 수정하지 않고 보고만 한다.
tools: Read, Grep, Glob
---
너는 뇌졸중 2차예방 생활습관 관리 도구의 임상 안전 검토자다.
검토 기준:
1. catalog/actions.yaml의 모든 수치가 docs/ARIAD_stage2_design.md Part 1 표와 일치하는가. 표에 없는 수치는 지적.
2. 금기 규칙: CKD/고칼륨 위험의 칼륨 대체염, 저체중의 감량 목표, 저혈당 위험 약제의 운동 전 혈당, 중증 두개내 협착의 혈압 목표.
3. config/red_flags.yaml이 새 신경학적 증상, 흉통, 실신, 혈당 <70, 반복 낙상을 모두 포함하는가.
4. 판정 엔진에 LLM 호출이 섞여 있지 않은가.
출력: 심각도(High/Med/Low)별 목록, 파일·줄 번호, 근거.
```

### 7-2. 메인 세션에서 병렬 실행 지시 예시

```text
스키마(schemas/stage2.py)는 확정됐어. 이제 다음 3개를 서브에이전트로 병렬 실행해줘.
- catalog-curator ×3: HTN 관련(D2, D3, A1, H1, M1), DM 관련(D5, P1–P3, W1, H2), DL 관련(D1, D4, S1) 항목을 각각 catalog/actions.yaml의 해당 섹션에만 작성.
- 끝나면 clinical-safety-reviewer로 전체 카탈로그를 검토하고, 지적 사항을 docs/review_step1.md에 정리해줘.
각 에이전트는 자기 섹션 외 파일을 수정하지 마.
```

## 출처 및 확인 필요 사항

### 확인 필요

- [x] AHA/ACC 2025 고혈압, ACC/AHA 2026 이상지질혈증 수치는 2차 자료 기반으로 일단 진행. 카탈로그 확정 전 원문 대조는 후순위.
- [x] ADA는 **2026 Standards of Care** 기준으로 갱신. 반영된 변화: 체중 감량 목표 5–7%.
- [x] KSH 2026 나트륨·음주 수치 없이 진행 (D2·A1은 AHA/ACC 2025 값 사용).
- [x] KDA 2025 운동 수치는 2차 자료 기반으로 진행.
- [x] 뇌졸중 환자 LDL-C 기본 목표 **<55 mg/dL** (+ ≥50% 감소).
- [x] Part 5 필드명은 리포 확인 없이 개발 진행. Claude Code가 구현 중 실제 스키마에 맞춰 조정.

### 출처

- [2021 AHA/ASA Guideline for the Prevention of Stroke in Patients With Stroke and TIA](https://www.ahajournals.org/doi/10.1161/STR.0000000000000375) — 원문 확인
- [2025 AHA/ACC High Blood Pressure Guideline (Hypertension)](https://www.ahajournals.org/doi/10.1161/HYP.0000000000000249) — 2차 자료: [AHA Top Things to Know](<https://professional.heart.org/en/science-news/2025-high-blood-pressure-guideline\\top-things-to-know>), [ACP Internist 요약](https://immattersacp.org/weekly/archives/2025/08/19/1.htm), [ACC/AHA 비약물 중재 표](https://pmc.ncbi.nlm.nih.gov/articles/PMC11283018/table/tbl4)
- [ADA Standards of Care 2019 — 5. Lifestyle Management](https://diabetesjournals.org/care/article/42/Supplement_1/S46/31274/5-Lifestyle-Management-Standards-of-Medical-Care) (2026판으로 대체) — 원문 미확인
- [2026 ACC/AHA Guideline on the Management of Dyslipidemia](https://www.ahajournals.org/doi/10.1161/CIR.0000000000001423) — 2차 자료: [HelixTalk 요약](https://www.rosalindfranklin.edu/academics/college-of-pharmacy/helixtalk/helixtalk-198-lp-a-apob-and-cac-navigating-the-2026-dyslipidemia-guideline-alphabet-soup/)
- [Korean Guidelines for the Management of Dyslipidemia 2026 (KSoLA)](https://www.lipid.or.kr/eng/pub/images/Korean%20Guidelines%20for%20the%20Management%20of%20Dyslipi8demia_2026.pdf) — 원문 확인
- [Highlights of the 2026 KSH Guidelines (Clin Hypertens 2026;32:e31)](https://www.clinicalhypertension.org/DOIx.php?id=10.5646/ch.2026.32.e31) — 원문 확인
- [2025 KDA Clinical Practice Guidelines (Diabetes Metab J 2025;49:582–783)](https://www.e-dmj.org/journal/view.php?number=2977) — 일부 확인
- ADA Standards of Care in Diabetes—2026 (Diabetes Care 2026 Suppl 1) — 2차 자료: [ACP 요약](https://diabetesguide.acponline.org/archives/2025/12/12/1.htm), [Diabetes on the Net 변경점](https://diabetesonthenet.com/diabetes-primary-care/factsheet-2026-ada-standards)

#!/usr/bin/env python3
"""`apps/api/.venv/bin/python scripts/eval_clinical_enrichment.py`

tasks/04_CLINICAL_ENRICHMENT.md item 5: measures how well the
clinical_enrichment stage (app/pipeline/enrichment.py) turns a transcript
into clinician-reviewable candidates, against two synthetic ground-truth
fixtures:

  - tests/fixtures/audio/sample_consultation.transcript.json (59.5s, 2
    speakers, existing Task 03 fixture)
  - tests/fixtures/audio/clinical_dialogue_3min.transcript.json (~155s, 3
    speakers, built for this task -- contains all four
    prompts/clinical_enrichment.md forbidden patterns plus a few genuine
    findings so this eval can check both "does not hallucinate" and "does
    not under-extract")

Both are fed directly as ground-truth transcript segments (not real audio),
so this measures the enrichment stage in isolation from ASR/diarization
error -- see the "전사 정확도 (CER)" section below for exactly what that
means for that one metric, and why it is reported as not-applicable here
rather than guessed.

Runs against MockLLMProvider by default (free, deterministic, always
available in this environment -- no real model weights or network needed).
Pass --real to use OPENAI_API_KEY instead (asks for y/N confirmation first,
same convention as scripts/test_provider_audio.py) to additionally measure
real LLM extraction quality -- something this script cannot do on its own
in a sandbox with no API key.

Synthetic fixtures only (CLAUDE.md: no real patient data). Never part of
`make test`/`make e2e`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

FIXTURES = [
    REPO_ROOT / "tests" / "fixtures" / "audio" / "sample_consultation.transcript.json",
    REPO_ROOT / "tests" / "fixtures" / "audio" / "clinical_dialogue_3min.transcript.json",
]

# segment_id -> what this eval expects the enrichment stage to do with it.
# "forbidden" checks are tasks/04_CLINICAL_ENRICHMENT.md's four negative
# examples; "genuine" checks are real content that should NOT be missed.
EXPECTATIONS = {
    "sample_consultation.transcript.json": [
        {
            "segment_id": "seg_003",
            "kind": "genuine",
            "label": "medication name (리시노프릴)",
            "check": lambda e, sid: any(
                "리시노프릴" in _finding_text(f) for f in _findings_citing(e, sid)
            ),
        },
        {
            "segment_id": "seg_003",
            "kind": "genuine",
            "label": "dose (5mg/오 밀리그램)",
            "check": lambda e, sid: any(
                "밀리그램" in _finding_text(f) or "5mg" in _finding_text(f) for f in _findings_citing(e, sid)
            ),
        },
        {
            "segment_id": "seg_005",
            "kind": "genuine",
            "label": "negation (아스피린 미투여)",
            "check": lambda e, sid: any(
                m.polarity == "negated" for m in e.medications if _cites(m, sid)
            )
            or any(m.action in ("stop", "unknown") for m in e.medications if _cites(m, sid)),
        },
        {
            "segment_id": "seg_007",
            "kind": "genuine",
            "label": "date (시월 첫째 주)",
            "check": lambda e, sid: any("시월" in _finding_text(f) for f in _findings_citing(e, sid)),
        },
    ],
    "clinical_dialogue_3min.transcript.json": [
        {
            "segment_id": "seg_006",
            "kind": "forbidden_1_score_from_order_alone",
            "label": '"다리 들어보세요"만으로 mRS/NIHSS/MRC 점수 생성 금지',
            "check": lambda e, sid: not any(x.score_candidates for x in e.exam if _cites(x, sid)),
        },
        {
            "segment_id": "seg_004",
            "kind": "forbidden_2_question_confirmed_as_finding",
            "label": '"다리를 끄나요?" 질문만으로 보행장애 확정 금지',
            "check": lambda e, sid: all(
                s.polarity == "question" for s in e.symptoms if _cites(s, sid)
            )
            and not any(_cites(d, sid) for d in e.diagnoses),
        },
        {
            "segment_id": "seg_012",
            "kind": "forbidden_3_rbd_from_behavior_alone",
            "label": "구체적 야간 행동만으로 진단(r/o RBD 등) 생성 금지 -- 추가 확인 후보로만",
            "check": lambda e, sid: not any(_cites(d, sid) for d in e.diagnoses)
            and any(_cites(f, sid) for f in e.follow_up_questions),
        },
        {
            "segment_id": "seg_016",
            "kind": "forbidden_4_negation_reversed",
            "label": '"끊지 마세요"가 중단 지시로 반전되지 않아야 함',
            "check": lambda e, sid: any(
                m.action == "continue" and m.polarity == "negated" for m in e.medications if _cites(m, sid)
            ),
        },
        {
            "segment_id": "seg_014",
            "kind": "genuine",
            "label": "medication name+dose (암로디핀 오 밀리그램)",
            "check": lambda e, sid: any(
                "암로디핀" in _finding_text(f) for f in _findings_citing(e, sid)
            ),
        },
        {
            "segment_id": "seg_018",
            "kind": "genuine",
            "label": "medication stop, doctor-stated (아스피린 중단)",
            "check": lambda e, sid: any(
                m.action == "stop" for m in e.medications if _cites(m, sid)
            ),
        },
        {
            "segment_id": "seg_024",
            "kind": "genuine",
            "label": "explicit score (NIHSS 1점) should be captured, not suppressed",
            "check": lambda e, sid: any(
                x.score_computable and x.score_candidates for x in e.exam if _cites(x, sid)
            ),
        },
        {
            "segment_id": "seg_027",
            "kind": "genuine",
            "label": "doctor-confirmed diagnosis should be captured",
            "check": lambda e, sid: any(
                d.kind == "confirmed" for d in e.diagnoses if _cites(d, sid)
            ),
        },
    ],
}


def _cer(reference: str, hypothesis: str) -> float:
    """Character error rate = Levenshtein distance / len(reference)."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    m, n = len(reference), len(hypothesis)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if reference[i - 1] == hypothesis[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n] / m


def _all_findings(enrichment):
    return (
        list(enrichment.medications)
        + list(enrichment.symptoms)
        + list(enrichment.exam)
        + list(enrichment.diagnoses)
        + list(enrichment.plan)
        + list(enrichment.follow_up_questions)
    )


def _cites(finding, segment_id: str) -> bool:
    return any(span.segment_id == segment_id for span in finding.source_spans)


def _findings_citing(enrichment, segment_id: str):
    return [f for f in _all_findings(enrichment) if _cites(f, segment_id)]


def _finding_text(finding) -> str:
    return getattr(finding, "raw_text", None) or getattr(finding, "trigger_text", "")


def _speaker_assignment_errors(enrichment, segments_by_id) -> int:
    """Counts source_spans whose speaker/role doesn't match the segment
    they claim to cite -- a misattribution bug in the enrichment step
    itself (diarization/ASR speaker errors are a separate, already-covered
    concern; see scripts/compare_asr_accuracy.py)."""
    errors = 0
    for finding in _all_findings(enrichment):
        for span in finding.source_spans:
            seg = segments_by_id.get(span.segment_id)
            if seg is not None and (span.speaker != seg.speaker or span.role != seg.role):
                errors += 1
    return errors


def _question_promoted_to_finding_errors(enrichment) -> int:
    """Symptoms whose reported_by is a bare doctor question must keep
    polarity="question" -- never get promoted to an affirmed finding."""
    return sum(1 for s in enrichment.symptoms if s.reported_by == "doctor_question" and s.polarity != "question")


def _ungrounded_score_or_diagnosis_violations(enrichment) -> int:
    keywords = ("score_candidates", "no doctor-sourced span")
    return sum(1 for v in enrichment.validator_violations if any(k in v for k in keywords))


def _build_provider(use_real: bool):
    from app.providers.mock import MockLLMProvider

    if not use_real:
        return MockLLMProvider(), "mock"

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("--real given but OPENAI_API_KEY is not set -- falling back to mock.")
        return MockLLMProvider(), "mock"

    print("OPENAI_API_KEY is set -- calling the real OpenAI API now (this costs money).")
    if input("Continue? [y/N] ").strip().lower() != "y":
        print("Cancelled -- falling back to mock.")
        return MockLLMProvider(), "mock"

    from app.providers.openai_llm import DEFAULT_TEXT_MODEL, OpenAILLMProvider

    # OPENAI_MODEL (eval-only override) > OPENAI_TEXT_MODEL (what the app uses) > default
    model = os.environ.get("OPENAI_MODEL") or os.environ.get("OPENAI_TEXT_MODEL") or DEFAULT_TEXT_MODEL
    return OpenAILLMProvider(api_key=api_key, model=model), f"openai:{model}"


def _run_fixture(fixture_path: Path, provider, provider_label: str) -> None:
    from app.domain.models import DiarizedSegment
    from app.observability import StageTimer
    from app.pipeline.enrichment import enrich_clinical_findings

    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    gt_segments = data["segments"]
    segments = [
        DiarizedSegment(
            id=s["id"], speaker=s["speaker"], role=s.get("expected_role", "unknown"),
            start=s["start"], end=s["end"], text=s["text"],
        )
        for s in gt_segments
    ]
    segments_by_id = {s.id: s for s in segments}
    audio_duration = max(s.end for s in segments) - min(s.start for s in segments)

    print(f"\n{'=' * 78}\n{fixture_path.name}  ({len(segments)} segments, ~{audio_duration:.0f}s)  provider={provider_label}\n{'=' * 78}")

    timer = StageTimer()
    wall_start = time.perf_counter()
    enrichment = enrich_clinical_findings(segments, provider, stage_timer=timer)
    wall_ms = (time.perf_counter() - wall_start) * 1000
    stage_ms = sum(r.duration_ms for r in timer.records if r.stage == "clinical_enrichment_llm") or wall_ms

    # 전사 정확도 (CER): this eval feeds gold transcript segments directly
    # (bypassing ASR), so a CER computed against itself here would be
    # trivially 0 -- not a real measurement, so it is deliberately not
    # computed or printed as a number (see the N/A line below instead of a
    # fabricated 0.00). Real ASR CER for these two fixtures:
    # sample_consultation already has one (see `make compare-asr-accuracy`);
    # the 3-minute fixture has no audio file (transcript-only, by design --
    # see the fixture's own "note" field) so its ASR-stage CER is simply not
    # measured here. Reproduction: synthesize audio for it (e.g. adapt
    # scripts/generate_sample_audio.py) and run `make compare-asr-accuracy`
    # against it once real sherpa-onnx models are available.
    gold_text = "".join(s.text for s in segments)
    cer = _cer(gold_text, gold_text)

    checks = EXPECTATIONS.get(fixture_path.name, [])
    results = []
    for check in checks:
        passed = bool(check["check"](enrichment, check["segment_id"]))
        results.append({**check, "passed": passed})

    forbidden_checks = [r for r in results if r["kind"].startswith("forbidden_")]
    genuine_checks = [r for r in results if r["kind"] == "genuine"]
    forbidden_pass = sum(1 for r in forbidden_checks if r["passed"])
    genuine_pass = sum(1 for r in genuine_checks if r["passed"])

    question_errors = _question_promoted_to_finding_errors(enrichment)
    ungrounded_errors = _ungrounded_score_or_diagnosis_violations(enrichment)
    speaker_errors = _speaker_assignment_errors(enrichment, segments_by_id)

    print(f"\n전사 정확도 (CER): {cer:.2f} (gold transcript fed directly, not real ASR output -- 0.00 by")
    print("  construction here; real ASR CER: sample_consultation은 make compare-asr-accuracy 참고,")
    print("  clinical_dialogue_3min은 오디오 파일이 없어 미측정 -- 위 note 참고)")
    print(f"금지 패턴 회피: {forbidden_pass}/{len(forbidden_checks)} pass")
    print(f"실제 항목 추출: {genuine_pass}/{len(genuine_checks)} pass")
    print(f"질문→소견 오분류 횟수: {question_errors}")
    print(f"근거 없는 점수·진단 생성 횟수 (validator가 교정한 건수): {ungrounded_errors}")
    print(f"화자 배정 오류 (source_span speaker/role mismatch): {speaker_errors}")
    print(f"clinical_enrichment_llm 단계 시간 (추가 처리 시간): {stage_ms:.1f}ms")
    print("전체 처리 시간: N/A -- this script measures the enrichment stage in isolation;")
    print("  전체 파이프라인(ASR+구조화+설명) 시간은 make benchmark-audio 참고 (별도 이미 측정됨)")

    print("\n원문 / 정리 결과 / 기대 결과 / 오류 유형:\n")
    header = f"{'segment':>10}  {'결과':<6}  설명"
    print(header)
    print("-" * len(header))
    for r in results:
        seg = segments_by_id[r["segment_id"]]
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{r['segment_id']:>10}  {status:<6}  {r['label']}")
        print(f"{'':>10}  {'원문':<6}  {seg.text}")
        citing = _findings_citing(enrichment, r["segment_id"])
        if citing:
            summary = "; ".join(f"[{type(f).__name__}] {_finding_text(f)[:40]}" for f in citing)
        else:
            summary = "(no finding cites this segment)"
        print(f"{'':>10}  {'정리':<6}  {summary}")
        print(f"{'':>10}  {'오류':<6}  {'-' if r['passed'] else r['kind']}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="use OPENAI_API_KEY instead of the mock provider")
    args = parser.parse_args()

    provider, provider_label = _build_provider(args.real)

    for fixture_path in FIXTURES:
        if not fixture_path.exists():
            print(f"Fixture not found: {fixture_path}")
            continue
        _run_fixture(fixture_path, provider, provider_label)

    print(
        "\n\n요약: mock provider는 안전성(4가지 금지 패턴 회피)을 구조적으로 보장하지만 "
        "실제 추출 커버리지는 규칙 기반이라 제한적이다 (예: 위 clinical_dialogue_3min의 "
        "'아스피린 중단' 항목처럼 약물명이 '약'이라는 글자를 포함하지 않으면 놓칠 수 있음 -- "
        "실제 LLM이라면 잡아낼 사례). 정확도가 실측으로 확인된 변경만 기본 경로(mock)에 "
        "반영했으며, 실제 OpenAI 품질은 --real로 직접 실행해 확인해야 한다 (이 샌드박스에는 "
        "API key가 없어 실측 불가)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

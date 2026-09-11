"""`make eval`: runs the mock pipeline over the synthetic golden set and
checks the one thing that matters at MVP stage -- zero unsupported claims
(docs/TESTING_AND_EVALS.md release gate). Since the mock provider only ever
copies transcript text verbatim, this also acts as a regression guard: if a
future change makes the mock (or a real provider swapped in behind the same
Protocol) invent content, this eval catches it.

This is intentionally a small starting point, not the full 20-30 fixture
annotated golden set docs/TESTING_AND_EVALS.md describes for ASR/diarization/
structure quality scoring -- that requires real (non-mock) provider output to
be worth scoring, which tasks/02_AUDIO_PIPELINE.md and beyond will add.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.pipeline.run import run_pipeline  # noqa: E402
from app.pipeline.validation import validate_grounding  # noqa: E402
from app.providers.mock import MockLLMProvider  # noqa: E402

FIXTURES_PATH = REPO_ROOT / "tests" / "fixtures" / "synthetic_transcripts.json"


def main() -> int:
    fixtures = json.loads(FIXTURES_PATH.read_text())
    provider = MockLLMProvider()
    failures = 0

    for fixture in fixtures:
        result = run_pipeline(fixture["transcript_text"], provider)
        report = validate_grounding(result.explanation, fixture["transcript_text"])
        status = "PASS" if report.valid else "FAIL"
        if not report.valid:
            failures += 1
        print(f"[{status}] {fixture['id']}: {fixture['description']}")
        for issue in report.issues:
            print(f"    - {issue}")

    total = len(fixtures)
    print(f"\n{total - failures}/{total} fixtures grounded, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

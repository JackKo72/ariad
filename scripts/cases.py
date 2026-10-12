"""Per-recording case folders (tasks/16_CASE_DATA_LAYOUT.md).

One folder per recording, named by the fictitious patient-matching number:

    apps/api/data/cases/er_3023432/          (gitignored -- never committed)
        er_3023432.wma            original recording, any format ffmpeg reads
        er_3023432.opus           make prepare-case-audio (mono 16 kHz)
        er_3023432.answer.txt     clinician answer transcript
        er_3023432.transcript.json  make answer-to-transcript
        er_3023432.emr.txt        anonymized chart -- reference for writing the
                                  gold ONLY; no app, eval or LLM call reads it
        er_3023432.meta.json      setting, frame, split, recording time (relative)

Helpers shared by check_cases.py, prepare_case_audio.py, migrate_case.py and
the eval scripts' CASE= shortcut. Never print file contents: callers print
names, counts and line numbers only.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = Path(os.environ.get("ARIAD_CASES_DIR", REPO_ROOT / "apps" / "api" / "data" / "cases"))
GOLD_DIR = REPO_ROOT / "tests" / "evals" / "gold"

CASE_ID = re.compile(r"^(er|icu|ward|opd)_\d{4,}$")
SETTINGS = ("er", "icu", "ward", "opd")
SPLITS = ("dev", "eval")
FRAMES = ("general_neuro", "stroke", "seizure", "headache", "dizziness", "movement", "cognitive",
          "neuromuscular", "spine", "icu")
AUDIO_SUFFIXES = (".wma", ".m4a", ".mp3", ".wav", ".mp4", ".ogg", ".webm", ".aac", ".amr", ".flac", ".opus")

# Anonymization check (lines are reported by number, never printed).
_PATTERNS = {
    "resident registration number": re.compile(r"\d{6}\s*-\s*[1-4]\d{6}"),
    "phone number": re.compile(r"\b01[016789][-\s]?\d{3,4}[-\s]?\d{4}\b|\b0\d{1,2}-\d{3,4}-\d{4}\b"),
    "calendar date (use D0, D+1, HD#2...)": re.compile(
        r"(19|20)\d{2}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}|\b\d{1,2}\s*월\s*\d{1,2}\s*일"),
    "long ID-like number": re.compile(r"(?<![\d.])\d{7,}(?![\d.])"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "name field": re.compile(r"(성명|이름|환자명|보호자명|담당의|주치의|작성자)\s*[:：]\s*\S"),
}


def case_dir(case: str) -> Path:
    return CASES_DIR / case


def case_file(case: str, suffix: str) -> Path:
    return case_dir(case) / f"{case}{suffix}"


def load_meta(case: str) -> Optional[dict[str, Any]]:
    path = case_file(case, ".meta.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def gold_path(case: str, meta: Optional[dict[str, Any]] = None) -> Path:
    """tests/evals/gold/<case>.gold.json, or the older gold a renamed case
    still uses (meta "gold_case", e.g. "sim_er_01")."""
    meta = meta if meta is not None else (load_meta(case) or {})
    return GOLD_DIR / f"{meta.get('gold_case') or case}.gold.json"


def transcript_for_gold(gold_case: str) -> Optional[Path]:
    """The case folder transcript scored against `gold_case` (folder named
    after it, or meta "gold_case" pointing to it)."""
    if not CASES_DIR.is_dir():
        return None
    for folder in sorted(p for p in CASES_DIR.iterdir() if p.is_dir()):
        meta = load_meta(folder.name) or {}
        if gold_case in (folder.name, meta.get("gold_case")):
            path = case_file(folder.name, ".transcript.json")
            if path.is_file():
                return path
    return None


def use_case_defaults(case: str) -> Optional[str]:
    """CASE= shortcut for the eval scripts: fills TRANSCRIPT, GOLD, FRAMES
    and OUTPUTS from the case folder unless already set. Returns an error
    message, or None."""
    if not case_dir(case).is_dir():
        return f"CASE={case}: {case_dir(case)} does not exist (docs/CASE_DATA.md)"
    meta = load_meta(case) or {}
    os.environ.setdefault("TRANSCRIPT", str(case_file(case, ".transcript.json")))
    os.environ.setdefault("GOLD", str(gold_path(case, meta)))
    if meta.get("frame"):
        os.environ.setdefault("FRAMES", meta["frame"])
    os.environ.setdefault("OUTPUTS", str(case_dir(case) / f"{case}.*.output.json"))
    return None


def find_audio(case: str) -> Optional[Path]:
    """The original recording (not the prepared .opus, unless it is the only one)."""
    found = [p for p in sorted(case_dir(case).glob(f"{case}.*")) if p.suffix.lower() in AUDIO_SUFFIXES]
    originals = [p for p in found if p.suffix.lower() != ".opus"]
    return (originals or found or [None])[0]


def validate_meta(case: str, meta: dict[str, Any]) -> list[str]:
    problems = []
    if meta.get("case") != case:
        problems.append(f'"case" must be "{case}" (the folder name)')
    if meta.get("setting") not in SETTINGS:
        problems.append(f'"setting" must be one of {", ".join(SETTINGS)}')
    if meta.get("split") not in SPLITS:
        problems.append('"split" must be "dev" or "eval"')
    if meta.get("frame") is not None and meta["frame"] not in FRAMES:
        problems.append(f'"frame" must be one of {", ".join(FRAMES)} (or left out)')
    if not meta.get("recorded_at"):
        problems.append('"recorded_at" missing (relative time, e.g. "D0 ER 도착 +2h, CT 후, 시술 결정 전")')
    return problems


def anonymization_flags(text: str, allowed_numbers: tuple[str, ...] = ()) -> dict[str, list[int]]:
    """{kind: [line numbers]} for anything that looks identifying.
    `allowed_numbers`: the case's own matching number."""
    flags: dict[str, list[int]] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _PATTERNS.items():
            hits = [m.group(0) for m in pattern.finditer(line)]
            if kind == "long ID-like number":
                hits = [h for h in hits if h not in allowed_numbers]
            if hits:
                flags.setdefault(kind, []).append(lineno)
    return flags

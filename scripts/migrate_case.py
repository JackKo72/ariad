#!/usr/bin/env python3
"""`make migrate-case OLD=sim_er_01 NEW=er_3023432 [FROM=apps/api/data/annotations]`

tasks/16: moves an already-analysed recording's files (<OLD>.*, e.g.
sim_er_01.opus, .answer.txt, .transcript.json, eval outputs) from the old
flat folder into cases/<NEW>/, renamed to <NEW>.*, and writes a starter
<NEW>.meta.json that keeps scoring against the existing gold
("gold_case": OLD). Fill in setting/frame/recorded_at afterwards; check
with make check-cases. Moves, never copies; refuses to overwrite.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import CASE_ID, REPO_ROOT, case_dir, case_file  # noqa: E402


def main() -> int:
    old, new = os.environ.get("OLD"), os.environ.get("NEW")
    if not old or not new:
        print("OLD and NEW must be set.\nUsage: make migrate-case OLD=sim_er_01 NEW=er_3023432")
        return 1
    if not CASE_ID.match(new):
        print(f"NEW={new}: should be <er|icu|ward|opd>_<number>, e.g. er_3023432")
        return 1
    source_dir = Path(os.environ.get("FROM", REPO_ROOT / "apps" / "api" / "data" / "annotations"))
    files = sorted(p for p in source_dir.glob(f"{old}.*") if p.is_file())
    if not files:
        print(f"no {old}.* files in {source_dir}")
        return 1
    target_dir = case_dir(new)
    target_dir.mkdir(parents=True, exist_ok=True)
    moves = [(p, target_dir / (new + p.name[len(old):])) for p in files]
    clash = [dst.name for _src, dst in moves if dst.exists()]
    if clash:
        print(f"refusing to overwrite in {target_dir}: {', '.join(clash)}")
        return 1
    for src, dst in moves:
        src.rename(dst)
        print(f"  {src.name} -> {target_dir.name}/{dst.name}")
    meta = case_file(new, ".meta.json")
    if not meta.exists():
        setting = new.split("_", 1)[0]
        meta.write_text(json.dumps({
            "case": new, "gold_case": old, "setting": setting, "frame": None, "split": "eval",
            "recorded_at": "", "speakers": [], "emr_scope": "", "notes": "",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  wrote {meta.name} (fill in frame, split, recorded_at)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

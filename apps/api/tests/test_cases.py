"""Unit: tasks/16 case folders (scripts/cases.py, check_cases.py,
migrate_case.py). Synthetic text only."""

import json
from pathlib import Path

import pytest


@pytest.fixture()
def cases(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import cases as module

    monkeypatch.setattr(module, "CASES_DIR", tmp_path / "cases")
    for var in ("TRANSCRIPT", "GOLD", "FRAMES", "OUTPUTS", "CASE"):
        monkeypatch.delenv(var, raising=False)
    return module


def test_identifying_patterns_are_flagged_by_line(cases):
    text = "\n".join([
        "D0 응급실 도착, CT 후 면담",          # 1 fine
        "등록번호 1234567 / 생년 900101-1234567",  # 2 long number + RRN
        "연락처 010-1234-5678",                # 3
        "2026-10-09 입원",                    # 4 calendar date
        "10월 9일 시술",                       # 5
        "주치의: 홍길동",                       # 6 name field
        "BP 120/80, Hb 9.8, case 3023432",     # 7 vitals fine, own number allowed
    ])
    flags = cases.anonymization_flags(text, ("3023432",))
    assert flags == {
        "long ID-like number": [2],
        "resident registration number": [2],
        "phone number": [3],
        "calendar date (use D0, D+1, HD#2...)": [4, 5],
        "name field": [6],
    }


def test_meta_validation(cases):
    good = {"case": "er_3023432", "setting": "er", "split": "eval", "frame": "stroke",
            "recorded_at": "D0 ER 도착 +2h"}
    assert cases.validate_meta("er_3023432", good) == []
    bad = {"case": "er_1", "setting": "clinic", "split": "test", "frame": "parkinson"}
    assert len(cases.validate_meta("er_3023432", bad)) == 5


def test_case_shortcut_fills_eval_inputs_and_legacy_gold(cases, monkeypatch):
    folder = cases.CASES_DIR / "er_3023432"
    folder.mkdir(parents=True)
    (folder / "er_3023432.meta.json").write_text(json.dumps(
        {"case": "er_3023432", "gold_case": "sim_er_01", "frame": "stroke"}), encoding="utf-8")
    (folder / "er_3023432.transcript.json").write_text('{"segments": []}', encoding="utf-8")
    assert cases.use_case_defaults("er_3023432") is None
    import os

    assert os.environ["TRANSCRIPT"].endswith("er_3023432/er_3023432.transcript.json")
    assert os.environ["GOLD"].endswith("tests/evals/gold/sim_er_01.gold.json")
    assert os.environ["FRAMES"] == "stroke"
    assert cases.transcript_for_gold("sim_er_01") == folder / "er_3023432.transcript.json"
    assert cases.use_case_defaults("er_9999999").startswith("CASE=er_9999999")


def test_migrate_moves_and_renames_and_writes_meta(cases, monkeypatch, tmp_path):
    import migrate_case

    monkeypatch.setattr(migrate_case, "case_dir", cases.case_dir)
    monkeypatch.setattr(migrate_case, "case_file", cases.case_file)
    old_dir = tmp_path / "annotations"
    old_dir.mkdir()
    for name in ("sim_er_01.opus", "sim_er_01.answer.txt", "sim_er_01.openai_gpt-4o.run1.output.json",
                 "sim_er_011.answer.txt"):
        (old_dir / name).write_text("x", encoding="utf-8")
    monkeypatch.setenv("OLD", "sim_er_01")
    monkeypatch.setenv("NEW", "er_3023432")
    monkeypatch.setenv("FROM", str(old_dir))
    assert migrate_case.main() == 0
    folder = cases.CASES_DIR / "er_3023432"
    assert sorted(p.name for p in folder.iterdir()) == [
        "er_3023432.answer.txt", "er_3023432.meta.json", "er_3023432.openai_gpt-4o.run1.output.json",
        "er_3023432.opus"]
    assert [p.name for p in old_dir.iterdir()] == ["sim_er_011.answer.txt"]  # another case untouched
    meta = json.loads((folder / "er_3023432.meta.json").read_text(encoding="utf-8"))
    assert (meta["case"], meta["gold_case"], meta["setting"]) == ("er_3023432", "sim_er_01", "er")
    assert migrate_case.main() == 1  # nothing left to move


def test_check_cases_reports_without_printing_contents(cases, monkeypatch, capsys):
    import check_cases

    for name in ("CASES_DIR",):
        monkeypatch.setattr(check_cases, name, cases.CASES_DIR)
    folder = cases.CASES_DIR / "icu_5550001"
    folder.mkdir(parents=True)
    (folder / "icu_5550001.emr.txt").write_text("D0 입원\n보호자 연락처 010-9876-5432\n", encoding="utf-8")
    (folder / "icu_5550001.meta.json").write_text(json.dumps(
        {"case": "icu_5550001", "setting": "icu", "split": "dev", "recorded_at": "HD#3 회진"}), encoding="utf-8")
    assert check_cases.main() == 1
    out = capsys.readouterr().out
    assert "icu_5550001.emr.txt: possible phone number on line 2" in out
    assert "010-9876-5432" not in out and "audio      MISSING" in out

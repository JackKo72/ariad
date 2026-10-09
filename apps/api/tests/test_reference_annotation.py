"""tasks/08_REAL_VOICE_REFERENCE_ANNOTATION.md: Audacity label parsing and
DER auto-discovery of <stem>.ref.json + <stem>.<audio> pairs. Synthetic
labels and the existing synthetic fixture only."""

import json
import shutil

import pytest


@pytest.fixture()
def scripts(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import eval_diarization_der
    import labels_to_reference

    return labels_to_reference, eval_diarization_der


GOOD = (
    "0.000\t3.500\tDOC|explain|오늘 상태를 설명드리겠습니다\n"
    "3.200\t5.000\tGUARD|other|네\n"  # overlaps DOC: allowed
    "6.000\t7.000\tBG1|other|\n"
    "\\\t0.000\t1000.000\n"  # Audacity spectral sub-line, ignored
)


def test_valid_labels_become_reference(scripts):
    labels_to_reference, _ = scripts
    segments, errors = labels_to_reference.parse_labels(GOOD)
    assert errors == []
    assert [s["speaker"] for s in segments] == ["DOC", "GUARD", "BG1"]
    assert [s["expected_role"] for s in segments] == ["doctor", "guardian", "background"]
    assert [s["background"] for s in segments] == [False, False, True]
    assert segments[0]["discourse"] == "explain"


def test_every_bad_line_is_reported(scripts):
    labels_to_reference, _ = scripts
    bad = (
        "0\t1\tA|?|draft label left unedited\n"
        "2\t2\tDOC|order|point label\n"
        "x\t3\tPT|exam|\n"
        "4\t5\tBG|other|\n"  # BG needs a number: one label per distinct voice
    )
    _segments, errors = labels_to_reference.parse_labels(bad)
    joined = "\n".join(errors)
    for expected in ("line 1: speaker 'A'", "line 1: type '?'", "line 2: end <= start", "line 3: start/end",
                     "line 4: speaker 'BG'"):
        assert expected in joined


def test_der_auto_discovers_reference_audio_pairs(scripts, tmp_path, monkeypatch):
    labels_to_reference, der = scripts
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available in this environment")
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "audio" / "sample_consultation.wav"
    shutil.copy(fixture, tmp_path / "sim_icu.wav")
    segments, _ = labels_to_reference.parse_labels(GOOD)
    (tmp_path / "sim_icu.ref.json").write_text(json.dumps({"segments": segments}))
    (tmp_path / "orphan.ref.json").write_text(json.dumps({"segments": segments}))  # no audio -> skipped

    oracle = {"skipped": False, "rtf": 0.0, "segments": [(s["start"], s["end"], s["speaker"]) for s in segments]}
    monkeypatch.setattr(der, "CANDIDATES", {"oracle": lambda _wav: oracle})
    monkeypatch.setenv("SET_DIR", str(tmp_path))
    monkeypatch.setenv("ENGINES", "oracle")
    monkeypatch.setenv("PREPROCESS", "none")

    assert der.main() == 0
    rows = json.loads((tmp_path / "der_results.json").read_text())["rows"]
    assert [(r["condition"], r["der"]) for r in rows] == [("sim_icu", 0.0)]

"""tasks/07_NOISY_DIARIZATION_EVAL.md: generate -> preprocess -> engine ->
score, end to end, with fake engines standing in for sherpa/pyannote/
Sortformer (no models in CI). An oracle engine that returns the reference
must score DER 0; one that lumps everything into a single cluster must leak
the neighbouring conversation into our speaker.

Synthetic fixtures only; the generated set lives in tmp_path."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"


@pytest.fixture(scope="module")
def noisy_set(tmp_path_factory) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available in this environment")
    out_dir = tmp_path_factory.mktemp("noisy_set")
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "generate_noisy_diarization_set.py")],
        env={**os.environ, "OUT_DIR": str(out_dir), "SNRS": "5"},
        check=True, capture_output=True,
    )
    return out_dir


@pytest.fixture()
def der_script(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS_DIR))
    import eval_diarization_der

    return eval_diarization_der


def _segments_of(ref_path: Path) -> list[tuple[float, float, str]]:
    return [(s["start"], s["end"], s["speaker"]) for s in json.loads(ref_path.read_text())["segments"]]


def test_set_has_clean_baseline_and_three_noise_kinds(noisy_set):
    manifest = json.loads((noisy_set / "manifest.json").read_text())
    assert [c["name"] for c in manifest["conditions"]] == [
        "clean", "music_snr5", "construction_snr5", "neighbour_snr5",
    ]
    neighbour = json.loads((noisy_set / "neighbour_snr5.ref.json").read_text())["segments"]
    assert any(s["background"] for s in neighbour)
    assert all("text" not in s for s in neighbour)  # speaker/time only


def test_oracle_engine_scores_zero_and_merged_engine_leaks(noisy_set, der_script, monkeypatch, capsys):
    current_ref: dict[str, Path] = {}

    def oracle(wav_path: Path) -> dict:
        return {"skipped": False, "rtf": 0.0, "segments": _segments_of(current_ref["path"])}

    def one_cluster(wav_path: Path) -> dict:
        segs = _segments_of(current_ref["path"])
        return {"skipped": False, "rtf": 0.0, "segments": [(s, e, "only") for s, e, _ in segs]}

    original_load = der_script.load_reference

    def tracking_load(path: Path):
        current_ref["path"] = path
        return original_load(path)

    monkeypatch.setattr(der_script, "load_reference", tracking_load)
    monkeypatch.setattr(der_script, "CANDIDATES", {"oracle": oracle, "one_cluster": one_cluster})
    monkeypatch.setenv("SET_DIR", str(noisy_set))
    monkeypatch.setenv("ENGINES", "oracle,one_cluster")
    monkeypatch.setenv("PREPROCESS", "none")

    assert der_script.main() == 0
    rows = json.loads((noisy_set / "der_results.json").read_text())["rows"]
    by_key = {(r["condition"], r["engine"]): r for r in rows}

    assert all(r["der"] == 0 for r in rows if r["engine"] == "oracle")
    assert by_key[("neighbour_snr5", "oracle")]["background_leakage"] == 0
    assert by_key[("neighbour_snr5", "one_cluster")]["background_leakage"] == 1.0
    assert by_key[("clean", "one_cluster")]["der"] > 0
    assert "리시노프릴" not in capsys.readouterr().out  # never prints transcript text

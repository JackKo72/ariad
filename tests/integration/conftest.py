import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def make_silence_wav(path: Path, duration_seconds: float = 1.0) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", str(duration_seconds), "-f", "wav", str(path),
        ],
        capture_output=True,
        check=True,
    )
    return path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "ariad_test.db"
    audio_dir = tmp_path / "audio"
    monkeypatch.setenv("ARIAD_DB_PATH", str(db_path))
    monkeypatch.setenv("ARIAD_AUDIO_DIR", str(audio_dir))
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def make_wav():
    return make_silence_wav


@pytest.fixture()
def approved_encounter(client):
    """An encounter carried through create -> input -> process -> approve.
    Returns (encounter_id, approved_version dict)."""
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(
        f"/encounters/{encounter_id}/input",
        json={"transcript_text": "의사: 혈압약 5mg 하루 한 번 복용하세요.\n환자: 네."},
    )
    r = client.post(f"/encounters/{encounter_id}/process")
    draft = r.json()["draft_version"]
    r = client.post(
        f"/encounters/{encounter_id}/approve",
        json={"expected_version_number": draft["version_number"]},
    )
    return encounter_id, r.json()["approved_version"]

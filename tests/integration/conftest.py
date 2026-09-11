import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "ariad_test.db"
    monkeypatch.setenv("ARIAD_DB_PATH", str(db_path))
    from app.main import app

    return TestClient(app)


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

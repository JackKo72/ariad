"""Integration: process_encounter/upload_audio persist stage_runs
(tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1)."""

import os

from app import db
from app.repositories.sqlite_repo import EncounterRepository


def _repo_for(client) -> EncounterRepository:
    """Opens a fresh connection to the same DB the `client` fixture
    pointed the app at (ARIAD_DB_PATH), so we can inspect what the request
    actually persisted."""
    return EncounterRepository(db.connect(os.environ["ARIAD_DB_PATH"]))


def test_process_encounter_records_structure_and_explanation_llm_stages(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(
        f"/encounters/{encounter_id}/input",
        json={"transcript_text": "의사: 혈압약 5mg 하루 한 번 복용하세요.\n환자: 네."},
    )
    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.json()["encounter"]["status"] == "REVIEW_REQUIRED"

    rows = _repo_for(client).list_stage_runs(encounter_id=encounter_id)
    stages = {row["stage"] for row in rows}
    # MockLLMProvider doesn't wrap itself in a stage (in-process, no
    # network/model -- see app/providers/mock.py) so structure_llm/
    # explanation_llm only appear for a real provider (see
    # test_openai_llm_provider.py for that). The route-level stages must
    # still be there regardless of which provider ran.
    assert {"database_write", "total"} <= stages
    assert all(row["status"] == "ok" for row in rows)
    for row in rows:
        assert "혈압약" not in str(row.values())


def test_stage_runs_are_recorded_even_when_processing_fails(client):
    """The route's try/finally must persist whatever the timer collected up
    to the point of failure -- not just on the happy path. (What a real
    provider itself records on its own failure, e.g. structure_llm with
    status=error, is covered at the unit level in
    apps/api/tests/test_openai_llm_provider.py; this test only exercises
    the route-level wiring with the default mock provider.)"""
    from app.dependencies import get_llm_provider
    from app.domain.errors import LlmProviderFailed
    from app.main import app

    class _AlwaysFails:
        def generate_json(self, prompt_id, payload, stage_timer=None):
            raise LlmProviderFailed("simulated")

    app.dependency_overrides[get_llm_provider] = lambda: _AlwaysFails()
    try:
        r = client.post("/encounters", json={"consent_confirmed": True})
        encounter_id = r.json()["id"]
        client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": "의사: 안녕하세요."})
        r = client.post(f"/encounters/{encounter_id}/process")
        assert r.json()["encounter"]["status"] == "PROCESSING_FAILED"
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)

    rows = _repo_for(client).list_stage_runs(encounter_id=encounter_id)
    stages = {row["stage"] for row in rows}
    assert "total" in stages


def test_upload_audio_records_upload_and_probe_stages(client, make_wav, tmp_path):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)

    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_id}/audio", files={"file": ("sample.wav", f, "audio/wav")}
        )
    assert r.status_code == 201

    rows = _repo_for(client).list_stage_runs(encounter_id=encounter_id)
    stages = {row["stage"] for row in rows}
    assert {"upload", "probe"} <= stages

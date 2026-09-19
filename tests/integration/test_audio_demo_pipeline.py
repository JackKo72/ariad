"""Integration: demo-mode audio pipeline end to end
(tasks/02_AUDIO_PIPELINE.md Phase C acceptance: "API key 없이 샘플 음성
사용으로 승인까지 전체 흐름이 동작한다")."""


def _select_sample(client, encounter_id):
    return client.post(
        f"/encounters/{encounter_id}/audio/sample", json={"sample_id": "sample_consultation"}
    )


def test_sample_selection_advances_to_submitted_with_pending_role_confirmation(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]

    r = _select_sample(client, encounter_id)
    assert r.status_code == 201
    body = r.json()
    assert body["pipeline_run"]["status"] == "needs_role_confirmation"
    assert len(body["pipeline_run"]["segments"]) == 10

    detail = client.get(f"/encounters/{encounter_id}").json()
    assert detail["encounter"]["status"] == "SUBMITTED"
    assert detail["active_pipeline_run"]["status"] == "needs_role_confirmation"


def test_process_before_role_confirmation_is_a_noop(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    _select_sample(client, encounter_id)

    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.status_code == 200
    assert r.json()["encounter"]["status"] == "SUBMITTED"
    assert r.json()["active_pipeline_run"]["status"] == "needs_role_confirmation"


def test_full_demo_flow_reaches_published(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    _select_sample(client, encounter_id)

    r = client.patch(
        f"/encounters/{encounter_id}/speaker-roles",
        json={"roles": {"A": "doctor", "B": "patient"}},
    )
    assert r.status_code == 200

    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.status_code == 200
    detail = r.json()
    assert detail["encounter"]["status"] == "REVIEW_REQUIRED"
    assert detail["active_pipeline_run"] is None  # run completed, no longer "active"

    draft = detail["draft_version"]
    assert "의사:" in draft["transcript_text"]
    assert "환자:" in draft["transcript_text"]
    assert draft["structure"]["medications"], "demo structure fixture should be used, not the empty mock"
    assert draft["explanation"]["current_situation"]

    r = client.post(
        f"/encounters/{encounter_id}/approve",
        json={"expected_version_number": draft["version_number"]},
    )
    assert r.status_code == 200, r.json()

    r = client.post(f"/encounters/{encounter_id}/publish")
    assert r.status_code == 200
    token = r.json()["encounter"]["public_token"]

    r = client.get(f"/public/explanations/{token}")
    assert r.status_code == 200
    assert r.json()["current_situation"]


def test_speaker_roles_reject_unknown_speaker_label(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    _select_sample(client, encounter_id)

    r = client.patch(
        f"/encounters/{encounter_id}/speaker-roles",
        json={"roles": {"Z": "doctor"}},
    )
    assert r.status_code == 404


def test_speaker_roles_without_active_run_is_not_found(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": "의사: 안녕하세요."})

    r = client.patch(
        f"/encounters/{encounter_id}/speaker-roles",
        json={"roles": {"A": "doctor"}},
    )
    assert r.status_code == 404


def test_arbitrary_upload_transcribe_returns_not_configured_and_manual_input_still_works(
    client, tmp_path, make_wav
):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_id}/audio",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    asset_id = r.json()["id"]

    r = client.post(f"/encounters/{encounter_id}/audio/{asset_id}/transcribe")
    assert r.status_code == 422
    assert r.json()["error_code"] == "ASR_NOT_CONFIGURED"

    # ASR failure must not have advanced the encounter or left it stuck.
    detail = client.get(f"/encounters/{encounter_id}").json()
    assert detail["encounter"]["status"] == "DRAFT"

    r = client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": "의사: 안녕하세요."})
    assert r.status_code == 200
    assert r.json()["encounter"]["status"] == "SUBMITTED"


def test_unknown_sample_id_returns_not_configured(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    r = client.post(
        f"/encounters/{encounter_id}/audio/sample", json={"sample_id": "does_not_exist"}
    )
    assert r.status_code == 422
    assert r.json()["error_code"] == "ASR_NOT_CONFIGURED"


def test_system_capabilities_reports_demo_mode_by_default(client):
    r = client.get("/system/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "demo"
    assert body["ffmpeg"] is True
    assert body["sample_audio"] is True
    assert body["asr"] == "demo"
    assert body["llm"] == "mock"
    assert "key" not in str(body).lower()

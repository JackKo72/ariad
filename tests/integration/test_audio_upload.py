"""Integration: audio upload + streaming against a real SQLite file and real
ffprobe (tasks/02_AUDIO_PIPELINE.md Phase A)."""


def test_upload_valid_wav_returns_metadata_without_hash(client, tmp_path, make_wav):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]

    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_id}/audio",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["encounter_id"] == encounter_id
    assert body["kind"] == "original"
    assert body["duration_seconds"] > 0
    assert "sha256_hash" not in body
    assert "storage_path" not in body


def test_upload_only_allowed_while_draft(client, tmp_path, make_wav):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": "의사: 안녕하세요."})

    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_id}/audio",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    assert r.status_code == 409
    assert r.json()["error_code"] == "STATE_TRANSITION_INVALID"


def test_upload_rejects_non_media_file(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]

    r = client.post(
        f"/encounters/{encounter_id}/audio",
        files={"file": ("fake.wav", b"not real audio content", "audio/wav")},
    )
    assert r.status_code == 422
    assert r.json()["error_code"] == "AUDIO_PROBE_FAILED"


def test_stream_returns_playable_audio_with_range_support(client, tmp_path, make_wav):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_id}/audio",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    asset_id = r.json()["id"]

    r = client.get(f"/encounters/{encounter_id}/audio/{asset_id}/stream")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    full_body = r.content

    r = client.get(
        f"/encounters/{encounter_id}/audio/{asset_id}/stream",
        headers={"Range": "bytes=0-99"},
    )
    assert r.status_code == 206
    assert len(r.content) == 100
    assert r.content == full_body[:100]


def test_stream_rejects_asset_from_a_different_encounter(client, tmp_path, make_wav):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_id}/audio",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    asset_id = r.json()["id"]

    r = client.post("/encounters", json={"consent_confirmed": True})
    other_encounter_id = r.json()["id"]

    r = client.get(f"/encounters/{other_encounter_id}/audio/{asset_id}/stream")
    assert r.status_code == 404

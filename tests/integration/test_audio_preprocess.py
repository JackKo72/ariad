"""Integration: audio preprocessing endpoint (tasks/02_AUDIO_PIPELINE.md
Phase B)."""


def test_preprocess_creates_a_processed_asset_distinct_from_original(client, tmp_path, make_wav):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_id}/audio",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    original = r.json()

    r = client.post(
        f"/encounters/{encounter_id}/audio/preprocess",
        json={"source_asset_id": original["id"], "mode": "light_denoise"},
    )
    assert r.status_code == 201
    processed = r.json()
    assert processed["id"] != original["id"]
    assert processed["kind"] == "processed"
    assert processed["preprocessing_mode"] == "light_denoise"
    assert processed["source_asset_id"] == original["id"]

    # Both remain independently streamable -- the original is untouched.
    r_original = client.get(f"/encounters/{encounter_id}/audio/{original['id']}/stream")
    r_processed = client.get(f"/encounters/{encounter_id}/audio/{processed['id']}/stream")
    assert r_original.status_code == 200
    assert r_processed.status_code == 200


def test_preprocess_mode_none_still_standardizes(client, tmp_path, make_wav):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_id}/audio",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    original = r.json()

    r = client.post(
        f"/encounters/{encounter_id}/audio/preprocess",
        json={"source_asset_id": original["id"], "mode": "none"},
    )
    assert r.status_code == 201
    assert r.json()["preprocessing_mode"] == "none"


def test_preprocess_rejects_source_from_a_different_encounter(client, tmp_path, make_wav):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_a = r.json()["id"]
    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_a}/audio",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    original = r.json()

    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_b = r.json()["id"]

    r = client.post(
        f"/encounters/{encounter_b}/audio/preprocess",
        json={"source_asset_id": original["id"], "mode": "none"},
    )
    assert r.status_code == 404


def test_preprocess_rejects_a_processed_asset_as_its_own_source(client, tmp_path, make_wav):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    wav_path = make_wav(tmp_path / "sample.wav", duration_seconds=1.0)
    with open(wav_path, "rb") as f:
        r = client.post(
            f"/encounters/{encounter_id}/audio",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    original = r.json()
    r = client.post(
        f"/encounters/{encounter_id}/audio/preprocess",
        json={"source_asset_id": original["id"], "mode": "none"},
    )
    processed = r.json()

    r = client.post(
        f"/encounters/{encounter_id}/audio/preprocess",
        json={"source_asset_id": processed["id"], "mode": "light_denoise"},
    )
    assert r.status_code == 404

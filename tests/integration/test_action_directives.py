"""Integration: POST /process fills ClinicalStructure.action_directives with
real segment IDs/speaker/role on both the manual-text and the segment-
carrying (audio-like) paths, and keeps them out of the patient explanation
and the public endpoint. Synthetic data only."""

from __future__ import annotations

import os

from app import db
from app.domain.models import DiarizedSegment
from app.repositories.sqlite_repo import EncounterRepository

TRANSCRIPT = "의사: 국물은 이제 드시지 마시고요.\n환자: 그게 제일 어렵네요. 혼자 살아서 라면을 자주 먹어요."


def _new_encounter(client) -> str:
    return client.post("/encounters", json={"consent_confirmed": True}).json()["id"]


def test_manual_text_process_stores_grounded_directives(client):
    encounter_id = _new_encounter(client)
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": TRANSCRIPT})
    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.status_code == 200
    draft = r.json()["draft_version"]
    assert draft["prompt_version_structure"] == "structure_transcript@0.2.0"

    [directive] = draft["structure"]["action_directives"]
    assert directive["raw_text"] == "국물은 이제 드시지 마시고요."
    span = directive["source_spans"][0]
    assert (span["segment_id"], span["speaker"], span["role"]) == ("seg_001", "의사", "doctor")
    assert directive["patient_response"]["agreement"] == "hesitant"
    # The patient explanation is built without stage 2 data.
    explanation_text = str(draft["explanation"])
    assert "어렵네요" in explanation_text  # mock copies transcript lines into current_situation
    assert "hesitant" not in explanation_text and "barrier" not in explanation_text


def test_segment_run_process_uses_real_ids_speaker_and_confirmed_role(client):
    encounter_id = _new_encounter(client)
    repo = EncounterRepository(db.connect(os.environ["ARIAD_DB_PATH"]))
    repo.create_pipeline_run(
        encounter_id, mode="manual", audio_asset_id=None, sample_id=None,
        segments=[
            DiarizedSegment(id="seg_011", speaker="A", start=0.0, end=2.0, text="주 5일 30분 걸으세요."),
            DiarizedSegment(id="seg_012", speaker="B", start=2.0, end=3.0, text="무릎이 아파서 힘들 것 같아요."),
        ],
    )
    repo.submit_input(encounter_id, "")
    client.patch(f"/encounters/{encounter_id}/speaker-roles", json={"roles": {"A": "doctor", "B": "patient"}})

    draft = client.post(f"/encounters/{encounter_id}/process").json()["draft_version"]
    [directive] = draft["structure"]["action_directives"]
    span = directive["source_spans"][0]
    assert (span["segment_id"], span["speaker"], span["role"]) == ("seg_011", "A", "doctor")
    assert directive["target_hint"] == "주 5일 30분"
    assert directive["barrier_mentions"][0]["source_spans"][0]["segment_id"] == "seg_012"
    assert [p["source_segment_ids"] for p in draft["structure"]["problems"]] == [["seg_011"], ["seg_012"]]


def test_public_endpoint_never_exposes_directives(client):
    encounter_id = _new_encounter(client)
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": TRANSCRIPT})
    draft = client.post(f"/encounters/{encounter_id}/process").json()["draft_version"]
    client.post(f"/encounters/{encounter_id}/approve", json={"expected_version_number": draft["version_number"]})
    token = client.post(f"/encounters/{encounter_id}/publish").json()["encounter"]["public_token"]
    body = client.get(f"/public/explanations/{token}").json()
    assert "action_directives" not in body and "structure" not in body


def test_draft_edit_keeps_directives_when_client_sends_them_back(client):
    encounter_id = _new_encounter(client)
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": TRANSCRIPT})
    draft = client.post(f"/encounters/{encounter_id}/process").json()["draft_version"]
    r = client.patch(
        f"/encounters/{encounter_id}/draft",
        json={"structure": draft["structure"], "explanation": draft["explanation"], "expected_version_number": draft["version_number"]},
    )
    assert r.json()["draft_version"]["structure"]["action_directives"] == draft["structure"]["action_directives"]

"""Integration: full encounter lifecycle against a real SQLite file
(docs/TESTING_AND_EVALS.md: API+DB, 승인/공개 권한). Mirrors
tasks/01_VERTICAL_SLICE.md acceptance criteria."""


def test_create_input_process_produces_review_required_draft(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    assert r.status_code == 201
    encounter_id = r.json()["id"]
    assert r.json()["status"] == "DRAFT"

    r = client.post(
        f"/encounters/{encounter_id}/input",
        json={"transcript_text": "의사: 오늘 혈압이 조금 높네요.\n환자: 요즘 짜게 먹었어요."},
    )
    assert r.status_code == 200
    assert r.json()["encounter"]["status"] == "SUBMITTED"

    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.status_code == 200
    detail = r.json()
    assert detail["encounter"]["status"] == "REVIEW_REQUIRED"
    assert detail["draft_version"]["structure"]["problems"], "mock structure should be non-empty"
    assert detail["draft_version"]["explanation"]["current_situation"]


def test_patch_draft_persists_clinician_edits(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": "의사: 검사를 진행할게요."})
    r = client.post(f"/encounters/{encounter_id}/process")
    draft = r.json()["draft_version"]

    edited_explanation = dict(draft["explanation"])
    edited_explanation["items_to_confirm_with_clinician"] = ["환자 성별 확인 필요"]
    r = client.patch(
        f"/encounters/{encounter_id}/draft",
        json={
            "structure": draft["structure"],
            "explanation": edited_explanation,
            "expected_version_number": draft["version_number"],
        },
    )
    assert r.status_code == 200
    assert r.json()["draft_version"]["explanation"]["items_to_confirm_with_clinician"] == [
        "환자 성별 확인 필요"
    ]
    assert r.json()["encounter"]["status"] == "REVIEW_REQUIRED"


def test_approve_creates_immutable_version_and_publish_exposes_it(client, approved_encounter):
    encounter_id, approved = approved_encounter
    r = client.get(f"/encounters/{encounter_id}")
    assert r.json()["encounter"]["status"] == "APPROVED"
    assert r.json()["approved_version"]["version_number"] == approved["version_number"]

    r = client.post(f"/encounters/{encounter_id}/publish")
    assert r.status_code == 200
    token = r.json()["encounter"]["public_token"]
    assert token

    r = client.get(f"/public/explanations/{token}")
    assert r.status_code == 200
    assert r.json() == approved["explanation"]


def test_state_persists_across_repeated_reads(client, approved_encounter):
    """Simulates a page refresh: repeated GETs return the same state."""
    encounter_id, _ = approved_encounter
    client.post(f"/encounters/{encounter_id}/publish")

    first = client.get(f"/encounters/{encounter_id}").json()
    second = client.get(f"/encounters/{encounter_id}").json()
    assert first == second
    assert first["encounter"]["status"] == "PUBLISHED"


def test_revoke_blocks_further_public_access(client, approved_encounter):
    encounter_id, _ = approved_encounter
    r = client.post(f"/encounters/{encounter_id}/publish")
    token = r.json()["encounter"]["public_token"]

    r = client.post(f"/encounters/{encounter_id}/revoke")
    assert r.status_code == 200
    assert r.json()["encounter"]["status"] == "REVOKED"

    r = client.get(f"/public/explanations/{token}")
    assert r.status_code == 404

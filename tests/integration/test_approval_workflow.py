"""Integration: approval immutability, grounding gate, and stale-version
conflicts (docs/PRODUCT.md section 6, docs/TESTING_AND_EVALS.md gates)."""


def test_editing_after_approval_creates_new_draft_without_changing_approved(client, approved_encounter):
    encounter_id, approved = approved_encounter

    edited = dict(approved["explanation"])
    edited["items_to_confirm_with_clinician"] = ["환자 나이 확인 필요"]
    r = client.patch(
        f"/encounters/{encounter_id}/draft",
        json={
            "structure": approved["structure"],
            "explanation": edited,
            "expected_version_number": approved["version_number"],
        },
    )
    assert r.status_code == 200
    detail = r.json()
    assert detail["encounter"]["status"] == "REVIEW_REQUIRED"
    assert detail["draft_version"]["version_number"] == approved["version_number"] + 1
    assert detail["approved_version"]["version_number"] == approved["version_number"]
    assert detail["approved_version"]["explanation"] == approved["explanation"]


def test_approve_rejects_stale_version_number(client, approved_encounter):
    encounter_id, approved = approved_encounter
    # approved_encounter already consumed version_number 1 to approve; the
    # encounter is now APPROVED, so approving again with a stale/mismatched
    # version must fail as a conflict, not silently succeed.
    r = client.post(
        f"/encounters/{encounter_id}/approve",
        json={"expected_version_number": approved["version_number"]},
    )
    assert r.status_code == 409


def test_approve_rejects_unsupported_claim_not_present_in_transcript(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(
        f"/encounters/{encounter_id}/input",
        json={"transcript_text": "의사: 혈압약 5mg 하루 한 번 복용하세요."},
    )
    r = client.post(f"/encounters/{encounter_id}/process")
    draft = r.json()["draft_version"]

    fabricated = dict(draft["explanation"])
    fabricated["medication_instructions"] = ["혈압약 10mg 하루 두 번 복용하세요"]
    r = client.patch(
        f"/encounters/{encounter_id}/draft",
        json={
            "structure": draft["structure"],
            "explanation": fabricated,
            "expected_version_number": draft["version_number"],
        },
    )
    draft2 = r.json()["draft_version"]

    r = client.post(
        f"/encounters/{encounter_id}/approve",
        json={"expected_version_number": draft2["version_number"]},
    )
    assert r.status_code == 422
    assert r.json()["error_code"] == "VALIDATION_UNSUPPORTED_CLAIM"


def test_publish_requires_approved_status(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    r = client.post(f"/encounters/{encounter_id}/publish")
    assert r.status_code == 409
    assert r.json()["error_code"] == "PUBLISH_NOT_APPROVED"

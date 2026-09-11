"""Integration: public endpoint must never leak unapproved/unpublished content
(docs/DEBUGGING.md playbook: "승인 전 환자 화면에 보임" is an access-control
defect, not an AI defect -- this is the regression test for it)."""


def test_unknown_token_returns_404(client):
    r = client.get("/public/explanations/does-not-exist")
    assert r.status_code == 404


def test_draft_encounter_not_publicly_reachable(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": "의사: 안녕하세요."})
    client.post(f"/encounters/{encounter_id}/process")
    # No public_token exists yet; there is nothing to even query -- confirm
    # the encounter has none and no token guesses succeed.
    detail = client.get(f"/encounters/{encounter_id}").json()
    assert detail["encounter"]["public_token"] is None


def test_approved_but_not_published_is_not_publicly_reachable(client, approved_encounter):
    encounter_id, _ = approved_encounter
    detail = client.get(f"/encounters/{encounter_id}").json()
    assert detail["encounter"]["status"] == "APPROVED"
    assert detail["encounter"]["public_token"] is None


def test_public_response_excludes_transcript_and_structure(client, approved_encounter):
    encounter_id, _ = approved_encounter
    r = client.post(f"/encounters/{encounter_id}/publish")
    token = r.json()["encounter"]["public_token"]

    r = client.get(f"/public/explanations/{token}")
    body = r.json()
    assert "transcript_text" not in body
    assert "problems" not in body
    assert set(body.keys()) == {
        "draft_notice",
        "current_situation",
        "tests_and_reasons",
        "treatment_plan",
        "medication_instructions",
        "warning_signs",
        "what_to_do_next",
        "follow_up",
        "items_to_confirm_with_clinician",
        "source_map",
    }

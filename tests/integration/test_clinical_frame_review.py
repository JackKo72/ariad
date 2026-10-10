"""Integration: clinical frame is recorded per version and approval is
gated on the clinician review checklist (tasks/10)."""

TRANSCRIPT = "의사: 막힌 혈관을 뚫는 시술은 지금은 안 하겠습니다.\n보호자: 네."


def _processed(client, body=None):
    encounter_id = client.post("/encounters", json={"consent_confirmed": True}).json()["id"]
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": TRANSCRIPT})
    r = client.post(f"/encounters/{encounter_id}/process", json=body) if body else client.post(
        f"/encounters/{encounter_id}/process")
    assert r.status_code == 200
    return encounter_id, r.json()


def test_process_without_body_still_works_and_records_no_frame(client):
    _, detail = _processed(client)
    assert detail["draft_version"]["clinical_frame"] is None
    assert detail["review_checklist"] == []


def test_process_records_selected_frame(client):
    _, detail = _processed(client, {"clinical_frame": "stroke"})
    assert detail["draft_version"]["clinical_frame"] == "stroke"


def test_unknown_frame_is_rejected(client):
    encounter_id = client.post("/encounters", json={"consent_confirmed": True}).json()["id"]
    client.post(f"/encounters/{encounter_id}/input", json={"transcript_text": TRANSCRIPT})
    assert client.post(f"/encounters/{encounter_id}/process", json={"clinical_frame": "cardiac"}).status_code == 422


def test_approval_requires_every_review_item_acknowledged(client):
    encounter_id, detail = _processed(client, {"clinical_frame": "stroke"})
    draft = detail["draft_version"]
    structure = {**draft["structure"], "decisions": [{
        "text": "막힌 혈관을 뚫는 시술", "status": "decided_not_to_do", "condition": "",
        "rationale": "", "source_segment_ids": ["seg-1"], "needs_confirmation": False}]}
    r = client.patch(f"/encounters/{encounter_id}/draft", json={
        "structure": structure, "explanation": draft["explanation"],
        "expected_version_number": draft["version_number"]})
    detail = r.json()
    checklist = detail["review_checklist"]
    assert [i["kind"] for i in checklist] == ["decision"]
    version = detail["draft_version"]["version_number"]

    r = client.post(f"/encounters/{encounter_id}/approve", json={"expected_version_number": version})
    assert r.status_code == 409 and r.json()["error_code"] == "REVIEW_CHECKLIST_INCOMPLETE"

    r = client.post(f"/encounters/{encounter_id}/approve", json={
        "expected_version_number": version, "acknowledged_review_item_ids": [checklist[0]["id"]]})
    assert r.status_code == 200 and r.json()["encounter"]["status"] == "APPROVED"
    assert r.json()["approved_version"]["clinical_frame"] == "stroke"

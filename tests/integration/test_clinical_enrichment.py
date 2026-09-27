"""Integration: process_encounter runs clinical_enrichment for audio-derived
(segment-carrying) pipeline runs and persists/returns it, without touching
the existing transcript_text/structure/explanation flow
(tasks/04_CLINICAL_ENRICHMENT.md)."""

from __future__ import annotations

import os

from app import db
from app.domain.models import DiarizedSegment
from app.repositories.sqlite_repo import EncounterRepository


def _repo_for(client) -> EncounterRepository:
    return EncounterRepository(db.connect(os.environ["ARIAD_DB_PATH"]))


_FORBIDDEN_PATTERN_SEGMENTS = [
    DiarizedSegment(id="s1", speaker="A", role="doctor", start=0.0, end=2.0, text="다리 들어보세요"),
    DiarizedSegment(id="s2", speaker="A", role="doctor", start=2.0, end=4.0, text="다리를 끄나요?"),
    DiarizedSegment(
        id="s3",
        speaker="B",
        role="patient",
        start=4.0,
        end=8.0,
        text="잠을 잘 못 자요. 잠꼬대로 소리를 지르고 팔다리를 휘두른다고 하더라고요.",
    ),
    DiarizedSegment(id="s4", speaker="A", role="doctor", start=8.0, end=10.0, text="약을 끊지 마세요."),
]


def _create_manual_pipeline_run(client, encounter_id: str, segments: list[DiarizedSegment]):
    repo = _repo_for(client)
    repo.create_pipeline_run(
        encounter_id, mode="manual", audio_asset_id=None, sample_id=None, segments=segments
    )
    repo.submit_input(encounter_id, "")


def test_process_encounter_populates_enrichment_for_segment_carrying_run(client):
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    _create_manual_pipeline_run(client, encounter_id, _FORBIDDEN_PATTERN_SEGMENTS)

    r = client.patch(
        f"/encounters/{encounter_id}/speaker-roles", json={"roles": {"A": "doctor", "B": "patient"}}
    )
    assert r.status_code == 200

    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.status_code == 200
    detail = r.json()
    assert detail["encounter"]["status"] == "REVIEW_REQUIRED"

    enrichment = detail["draft_version"]["enrichment"]
    assert enrichment is not None

    # Forbidden pattern 1: an exam order alone must never produce a score.
    assert enrichment["exam"], "다리 들어보세요 should be captured as an exam order"
    assert enrichment["exam"][0]["score_computable"] is False
    assert enrichment["exam"][0]["score_candidates"] == []

    # Forbidden pattern 2: a bare doctor question must stay a question, never
    # get promoted into an affirmed symptom or a diagnosis.
    questions = [s for s in enrichment["symptoms"] if s["reported_by"] == "doctor_question"]
    assert questions and questions[0]["polarity"] == "question"

    # Forbidden pattern 3: specific nocturnal behavior must never become a
    # diagnosis (e.g. RBD) -- only a follow_up_questions suggestion.
    assert enrichment["diagnoses"] == []
    assert enrichment["follow_up_questions"], "nocturnal behavior should surface as a follow-up question"

    # Forbidden pattern 4: "끊지 마세요" must not flip to a stop action.
    assert enrichment["medications"]
    assert enrichment["medications"][0]["action"] == "continue"
    assert enrichment["medications"][0]["polarity"] == "negated"

    # validator ran and found nothing to correct against this safe mock output.
    assert enrichment["validator_violations"] == []

    # Existing structure_llm/explanation_llm/transcript_text flow untouched.
    assert detail["draft_version"]["structure"] is not None
    assert detail["draft_version"]["explanation"] is not None


def test_manual_text_only_encounter_has_no_enrichment(client):
    """No segment-level speaker/time metadata to anchor findings to --
    enrichment must stay None, not an empty-but-present object."""
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(
        f"/encounters/{encounter_id}/input",
        json={"transcript_text": "의사: 혈압약 5mg 하루 한 번 복용하세요.\n환자: 네."},
    )
    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.json()["draft_version"]["enrichment"] is None


def test_demo_mode_has_no_enrichment(client):
    """Demo mode uses a pre-canned structure/explanation fixture and never
    calls the real pipeline -- enrichment must stay None there too."""
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    client.post(f"/encounters/{encounter_id}/audio/sample", json={"sample_id": "sample_consultation"})
    client.patch(
        f"/encounters/{encounter_id}/speaker-roles", json={"roles": {"A": "doctor", "B": "patient"}}
    )
    r = client.post(f"/encounters/{encounter_id}/process")
    assert r.json()["draft_version"]["enrichment"] is None


def test_editing_approved_draft_carries_enrichment_forward(client):
    """update_draft's clone-from-approved path must not silently drop the
    enrichment that was already computed against the (unchanged) original
    transcript -- the stage isn't re-run on a structure/explanation edit."""
    r = client.post("/encounters", json={"consent_confirmed": True})
    encounter_id = r.json()["id"]
    _create_manual_pipeline_run(client, encounter_id, _FORBIDDEN_PATTERN_SEGMENTS)
    client.patch(
        f"/encounters/{encounter_id}/speaker-roles", json={"roles": {"A": "doctor", "B": "patient"}}
    )
    r = client.post(f"/encounters/{encounter_id}/process")
    draft = r.json()["draft_version"]
    assert draft["enrichment"] is not None

    r = client.post(
        f"/encounters/{encounter_id}/approve", json={"expected_version_number": draft["version_number"]}
    )
    approved = r.json()["approved_version"]

    r = client.patch(
        f"/encounters/{encounter_id}/draft",
        json={
            "structure": approved["structure"],
            "explanation": approved["explanation"],
            "expected_version_number": approved["version_number"],
        },
    )
    assert r.status_code == 200
    new_draft = r.json()["draft_version"]
    assert new_draft["enrichment"] is not None
    assert new_draft["enrichment"] == approved["enrichment"]

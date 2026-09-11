"""Clinician-facing encounter routes (docs/ARCHITECTURE.md section 4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.domain.errors import ValidationUnsupportedClaim
from app.domain.models import ClinicalStructure, Encounter, EncounterDetail, ExplanationDraft
from app.pipeline.run import run_pipeline
from app.pipeline.validation import validate_grounding
from app.providers.mock import MockLLMProvider
from app.repositories.sqlite_repo import EncounterRepository

from app.dependencies import get_llm_provider, get_repository

router = APIRouter(prefix="/encounters", tags=["encounters"])


class CreateEncounterRequest(BaseModel):
    consent_confirmed: bool


class SubmitInputRequest(BaseModel):
    transcript_text: str = Field(min_length=1)


class UpdateDraftRequest(BaseModel):
    structure: ClinicalStructure
    explanation: ExplanationDraft
    expected_version_number: int


class ApproveRequest(BaseModel):
    expected_version_number: int


def _to_detail(repo: EncounterRepository, encounter: Encounter) -> EncounterDetail:
    draft_version = (
        repo.get_version(encounter.current_draft_version_id)
        if encounter.current_draft_version_id
        else None
    )
    approved_version = (
        repo.get_version(encounter.approved_version_id) if encounter.approved_version_id else None
    )
    return EncounterDetail(encounter=encounter, draft_version=draft_version, approved_version=approved_version)


@router.get("", response_model=list[Encounter])
def list_encounters(repo: EncounterRepository = Depends(get_repository)) -> list[Encounter]:
    return repo.list_encounters()


@router.post("", response_model=Encounter, status_code=201)
def create_encounter(
    body: CreateEncounterRequest, repo: EncounterRepository = Depends(get_repository)
) -> Encounter:
    return repo.create_encounter(consent_confirmed=body.consent_confirmed)


@router.get("/{encounter_id}", response_model=EncounterDetail)
def get_encounter(
    encounter_id: str, repo: EncounterRepository = Depends(get_repository)
) -> EncounterDetail:
    encounter = repo.get_encounter(encounter_id)
    return _to_detail(repo, encounter)


@router.post("/{encounter_id}/input", response_model=EncounterDetail)
def submit_input(
    encounter_id: str,
    body: SubmitInputRequest,
    repo: EncounterRepository = Depends(get_repository),
) -> EncounterDetail:
    encounter = repo.submit_input(encounter_id, body.transcript_text)
    return _to_detail(repo, encounter)


@router.post("/{encounter_id}/process", response_model=EncounterDetail)
def process_encounter(
    encounter_id: str,
    repo: EncounterRepository = Depends(get_repository),
    llm_provider: MockLLMProvider = Depends(get_llm_provider),
) -> EncounterDetail:
    encounter = repo.start_processing(encounter_id)
    draft = repo.get_version(encounter.current_draft_version_id)  # type: ignore[arg-type]

    try:
        result = run_pipeline(draft.transcript_text, llm_provider)
    except Exception:
        encounter = repo.fail_processing(encounter_id, error_code="SIMPLIFICATION_PROVIDER_FAILED")
        return _to_detail(repo, encounter)

    from app.pipeline.structure import PROMPT_VERSION as STRUCTURE_PROMPT_VERSION
    from app.pipeline.explanation import PROMPT_VERSION as EXPLANATION_PROMPT_VERSION

    encounter = repo.complete_processing(
        encounter_id,
        structure=result.structure,  # type: ignore[arg-type]
        explanation=result.explanation,  # type: ignore[arg-type]
        prompt_version_structure=STRUCTURE_PROMPT_VERSION,
        prompt_version_explanation=EXPLANATION_PROMPT_VERSION,
    )
    return _to_detail(repo, encounter)


@router.patch("/{encounter_id}/draft", response_model=EncounterDetail)
def update_draft(
    encounter_id: str,
    body: UpdateDraftRequest,
    repo: EncounterRepository = Depends(get_repository),
) -> EncounterDetail:
    encounter = repo.update_draft(
        encounter_id,
        structure=body.structure,
        explanation=body.explanation,
        expected_version_number=body.expected_version_number,
    )
    return _to_detail(repo, encounter)


@router.post("/{encounter_id}/approve", response_model=EncounterDetail)
def approve_encounter(
    encounter_id: str,
    body: ApproveRequest,
    repo: EncounterRepository = Depends(get_repository),
) -> EncounterDetail:
    encounter = repo.get_encounter(encounter_id)
    draft = repo.get_version(encounter.current_draft_version_id)  # type: ignore[arg-type]
    report = validate_grounding(draft.explanation, draft.transcript_text)
    if not report.valid:
        raise ValidationUnsupportedClaim("; ".join(report.issues))

    encounter = repo.approve(encounter_id, expected_version_number=body.expected_version_number)
    return _to_detail(repo, encounter)


@router.post("/{encounter_id}/publish", response_model=EncounterDetail)
def publish_encounter(
    encounter_id: str, repo: EncounterRepository = Depends(get_repository)
) -> EncounterDetail:
    encounter = repo.publish(encounter_id)
    return _to_detail(repo, encounter)


@router.post("/{encounter_id}/revoke", response_model=EncounterDetail)
def revoke_encounter(
    encounter_id: str, repo: EncounterRepository = Depends(get_repository)
) -> EncounterDetail:
    encounter = repo.revoke(encounter_id)
    return _to_detail(repo, encounter)

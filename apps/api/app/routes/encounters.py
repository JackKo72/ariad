"""Clinician-facing encounter routes (docs/ARCHITECTURE.md section 4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.domain.errors import NotFoundError, ValidationUnsupportedClaim
from app.domain.models import (
    ClinicalStructure,
    Encounter,
    EncounterDetail,
    ExplanationDraft,
    PipelineRun,
)
from app.pipeline.run import run_pipeline
from app.pipeline.validation import validate_grounding
from app.providers.demo_asr import load_demo_structure_and_explanation
from app.providers.mock import MockLLMProvider
from app.repositories.sqlite_repo import EncounterRepository

from app.dependencies import get_llm_provider, get_repository

router = APIRouter(prefix="/encounters", tags=["encounters"])

_ROLE_LABELS_KO = {
    "doctor": "의사",
    "patient": "환자",
    "guardian": "보호자",
    "unknown": "화자",
}


def _derive_transcript_text(run: PipelineRun) -> str:
    lines = []
    for seg in sorted(run.segments, key=lambda s: s.start):
        role = run.roles.get(seg.speaker, "unknown")
        label = _ROLE_LABELS_KO.get(role, "화자")
        lines.append(f"{label}: {seg.text}")
    return "\n".join(lines)


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
    active_pipeline_run = repo.get_active_pipeline_run(encounter.id)
    return EncounterDetail(
        encounter=encounter,
        draft_version=draft_version,
        approved_version=approved_version,
        active_pipeline_run=active_pipeline_run,
    )


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


class SpeakerRolesRequest(BaseModel):
    roles: dict[str, str]  # speaker label -> "doctor" | "patient" | "guardian" | "unknown"


@router.patch("/{encounter_id}/speaker-roles", response_model=EncounterDetail)
def set_speaker_roles(
    encounter_id: str,
    body: SpeakerRolesRequest,
    repo: EncounterRepository = Depends(get_repository),
) -> EncounterDetail:
    """Clinician confirms/edits the doctor/patient/guardian role for each
    detected speaker before structuring can run (tasks/02_AUDIO_PIPELINE.md
    section 8: role assignment is never auto-confirmed)."""
    active_run = repo.get_active_pipeline_run(encounter_id)
    if active_run is None:
        raise NotFoundError("PipelineRun")
    repo.set_pipeline_run_roles(active_run.id, body.roles)
    return _to_detail(repo, repo.get_encounter(encounter_id))


@router.post("/{encounter_id}/process", response_model=EncounterDetail)
def process_encounter(
    encounter_id: str,
    repo: EncounterRepository = Depends(get_repository),
    llm_provider: MockLLMProvider = Depends(get_llm_provider),
) -> EncounterDetail:
    active_run = repo.get_active_pipeline_run(encounter_id)

    if active_run is not None and active_run.status == "needs_role_confirmation":
        if not active_run.roles:
            # Never auto-continue past role assignment -- stay put until
            # PATCH /speaker-roles has been called.
            return _to_detail(repo, repo.get_encounter(encounter_id))
        repo.update_draft_transcript_text(encounter_id, _derive_transcript_text(active_run))

    encounter = repo.start_processing(encounter_id)
    draft = repo.get_version(encounter.current_draft_version_id)  # type: ignore[arg-type]

    try:
        if active_run is not None and active_run.mode == "demo":
            structure, explanation = load_demo_structure_and_explanation(active_run.sample_id)  # type: ignore[arg-type]
        else:
            result = run_pipeline(draft.transcript_text, llm_provider)
            structure, explanation = result.structure, result.explanation  # type: ignore[assignment]
    except Exception:
        encounter = repo.fail_processing(encounter_id, error_code="SIMPLIFICATION_PROVIDER_FAILED")
        return _to_detail(repo, encounter)

    from app.pipeline.structure import PROMPT_VERSION as STRUCTURE_PROMPT_VERSION
    from app.pipeline.explanation import PROMPT_VERSION as EXPLANATION_PROMPT_VERSION

    encounter = repo.complete_processing(
        encounter_id,
        structure=structure,  # type: ignore[arg-type]
        explanation=explanation,  # type: ignore[arg-type]
        prompt_version_structure=STRUCTURE_PROMPT_VERSION,
        prompt_version_explanation=EXPLANATION_PROMPT_VERSION,
    )

    if active_run is not None:
        repo.complete_pipeline_run(active_run.id)

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

"""Core data shapes shared across routes, pipeline, and repository layers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class EncounterStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    REVOKED = "REVOKED"


class VersionStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"


class ClinicalStructure(BaseModel):
    problems: list[dict[str, Any]] = Field(default_factory=list)
    tests: list[dict[str, Any]] = Field(default_factory=list)
    medications: list[dict[str, Any]] = Field(default_factory=list)
    plan: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    follow_up: list[dict[str, Any]] = Field(default_factory=list)
    questions_or_conflicts: list[str] = Field(default_factory=list)


class ExplanationDraft(BaseModel):
    draft_notice: str = ""
    current_situation: list[str] = Field(default_factory=list)
    tests_and_reasons: list[str] = Field(default_factory=list)
    treatment_plan: list[str] = Field(default_factory=list)
    medication_instructions: list[str] = Field(default_factory=list)
    warning_signs: list[str] = Field(default_factory=list)
    what_to_do_next: list[str] = Field(default_factory=list)
    follow_up: list[str] = Field(default_factory=list)
    items_to_confirm_with_clinician: list[str] = Field(default_factory=list)
    source_map: list[dict[str, Any]] = Field(default_factory=list)


class ValidationReport(BaseModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)


class EncounterVersion(BaseModel):
    id: str
    encounter_id: str
    version_number: int
    status: VersionStatus
    transcript_text: str
    structure: ClinicalStructure
    explanation: ExplanationDraft
    prompt_version_structure: Optional[str] = None
    prompt_version_explanation: Optional[str] = None
    created_at: str
    approved_at: Optional[str] = None


class Encounter(BaseModel):
    id: str
    status: EncounterStatus
    consent_confirmed: bool
    error_code: Optional[str] = None
    public_token: Optional[str] = None
    current_draft_version_id: Optional[str] = None
    approved_version_id: Optional[str] = None
    created_at: str
    updated_at: str


class DiarizedSegment(BaseModel):
    """One turn from ASRProvider.transcribe() (tasks/02_AUDIO_PIPELINE.md
    section 8). `role`/`role_confidence` start unknown -- diarization only
    clusters speakers into labels (A/B/C); a clinician assigns the clinical
    role via PATCH /speaker-roles before structuring ever runs."""

    id: str
    speaker: str
    role: str = "unknown"
    role_confidence: Optional[float] = None
    start: float
    end: float
    text: str


class PipelineRun(BaseModel):
    """Tracks one audio-derived encounter's ASR/diarization/role-assignment
    state, orthogonal to EncounterStatus (docs/AI_PIPELINE.md staging).
    Completing a run hands off to the existing Task 01
    structure/explanation path -- it never replaces it."""

    id: str
    encounter_id: str
    mode: str  # "demo" | "manual" | "provider"
    status: str  # "needs_role_confirmation" | "completed"
    audio_asset_id: Optional[str] = None
    sample_id: Optional[str] = None
    segments: list[DiarizedSegment] = Field(default_factory=list)
    roles: dict[str, str] = Field(default_factory=dict)  # speaker label -> role
    error_code: Optional[str] = None
    created_at: str
    updated_at: str


class EncounterDetail(BaseModel):
    encounter: Encounter
    draft_version: Optional[EncounterVersion] = None
    approved_version: Optional[EncounterVersion] = None
    active_pipeline_run: Optional[PipelineRun] = None


class AudioAsset(BaseModel):
    """API-facing shape for an uploaded/processed audio file.

    Deliberately has no hash field -- docs/... task 02 section 5: "사용자에게
    원본 hash를 공개하지 않는다". The hash lives only in the DB row.
    """

    id: str
    encounter_id: str
    kind: str  # "original" | "processed"
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: int
    duration_seconds: float
    preprocessing_mode: Optional[str] = None  # None for "original"; "none" | "light_denoise" for "processed"
    source_asset_id: Optional[str] = None  # the "original" asset a "processed" one was derived from
    sample_id: Optional[str] = None  # non-null if this came from the built-in demo sample library
    created_at: str


class SampleSelectionResult(BaseModel):
    audio_asset: AudioAsset
    pipeline_run: PipelineRun


class PipelineResult(BaseModel):
    success: bool
    structure: Optional[ClinicalStructure] = None
    explanation: Optional[ExplanationDraft] = None
    validation: Optional[ValidationReport] = None
    error_code: Optional[str] = None

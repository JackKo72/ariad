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


class EncounterDetail(BaseModel):
    encounter: Encounter
    draft_version: Optional[EncounterVersion] = None
    approved_version: Optional[EncounterVersion] = None


class PipelineResult(BaseModel):
    success: bool
    structure: Optional[ClinicalStructure] = None
    explanation: Optional[ExplanationDraft] = None
    validation: Optional[ValidationReport] = None
    error_code: Optional[str] = None

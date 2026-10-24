"""Core data shapes shared across routes, pipeline, and repository layers."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

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


# Nested shapes mirror packages/contracts/schema/clinical_structure.schema.json
# and explanation_draft.schema.json exactly (field names, required-ness,
# enums). This is not just documentation -- OpenAI's structured-output
# strict mode (app/providers/openai_llm.py) rejects a free-form
# `dict[str, Any]` field (it collapses to an object schema with no declared
# properties, which the API then refuses with "'required' ... including
# every key in properties"), so every nested object needs an explicit model.
class Problem(BaseModel):
    text: str
    certainty: Literal["stated", "uncertain"]
    source_segment_ids: list[str] = Field(default_factory=list)


class TestOrder(BaseModel):
    name: str
    reason: str
    status: Literal["planned", "completed", "unknown"]
    source_segment_ids: list[str] = Field(default_factory=list)


class Medication(BaseModel):
    name: str
    dose: str
    route: str
    frequency: str
    action: Literal["start", "continue", "stop", "unknown"]
    source_segment_ids: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False


class PlanItem(BaseModel):
    text: str
    source_segment_ids: list[str] = Field(default_factory=list)


class SourceMapEntry(BaseModel):
    field: str
    source_segment_ids: list[str] = Field(default_factory=list)


class ClinicalStructure(BaseModel):
    problems: list[Problem] = Field(default_factory=list)
    tests: list[TestOrder] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    plan: list[PlanItem] = Field(default_factory=list)
    warnings: list[PlanItem] = Field(default_factory=list)
    follow_up: list[PlanItem] = Field(default_factory=list)
    questions_or_conflicts: list[str] = Field(default_factory=list)
    # Stage 2 additive field (docs/stage1_output.md section 6, option C).
    # Defaults to [] so stored versions and demo fixtures without it still load.
    action_directives: list[ActionDirective] = Field(default_factory=list)


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
    source_map: list[SourceMapEntry] = Field(default_factory=list)


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
    # None for manual text-only encounters/demo mode (no segment-level
    # speaker/time metadata to anchor findings to) -- additive field, never
    # required, so it never breaks existing API consumers.
    enrichment: Optional[ClinicalEnrichment] = None
    prompt_version_structure: Optional[str] = None
    prompt_version_explanation: Optional[str] = None
    prompt_version_enrichment: Optional[str] = None
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


class NormalizedCandidate(BaseModel):
    """One normalization guess for an ambiguous raw utterance (e.g. a
    medication name or dose). Never collapse ambiguity into one value --
    tasks/04_CLINICAL_ENRICHMENT.md: a clinician picks among candidates,
    the model never silently picks for them."""

    value: str
    confidence: Literal["high", "medium", "low"] = "low"


class SourceSpan(BaseModel):
    """Links one enrichment finding back to the exact transcript segment
    and verbatim quote it came from (never edited/paraphrased) plus who
    said it and, if the segment carries times, when."""

    segment_id: str
    quote: str
    speaker: str
    role: str = "unknown"
    start: Optional[float] = None
    end: Optional[float] = None


# Stage 2 extension of ClinicalStructure (docs/ARIAD_stage2_design.md Part
# 5-2): lifestyle directives the doctor gave, with the patient's reply and
# barriers, each tied to real segments via SourceSpan. Re-exported from
# app.domain.stage2.
class Agreement(str, Enum):
    """How the patient responded to a directive in the visit (Part 5-2).
    Clinical information -- distinct from needs_review, which is about
    extraction quality (docs/stage1_output.md section 7, item 10)."""

    AGREED = "agreed"
    HESITANT = "hesitant"
    REFUSED = "refused"
    UNCLEAR = "unclear"


class PatientResponse(BaseModel):
    text: str  # verbatim
    agreement: Agreement
    source_spans: list[SourceSpan] = Field(default_factory=list)


class BarrierMention(BaseModel):
    text: str  # verbatim
    source_spans: list[SourceSpan] = Field(default_factory=list)


class ActionDirective(BaseModel):
    """One lifestyle directive the doctor gave in the visit (Part 5-2).

    raw_text is copied verbatim, never paraphrased. source_spans must point
    at real input segments; app/pipeline/directive_validation.py enforces that and sets
    needs_review instead of failing the whole structure output, so no
    hard length constraint here. domain_hint/target_hint are hints only --
    the normalizer does the final catalog match."""

    directive_id: str
    raw_text: str
    source_spans: list[SourceSpan] = Field(default_factory=list)
    domain_hint: Optional[str] = None
    target_hint: Optional[str] = None
    patient_response: Optional[PatientResponse] = None
    barrier_mentions: list[BarrierMention] = Field(default_factory=list)
    needs_review: bool = True


# affirmed: stated as true. negated: explicitly denied/negative.
# question: asked, not yet answered/confirmed. uncertain: hedged ("아마",
# "잘 모르겠어요") or the model itself isn't sure which of the above applies.
Polarity = Literal["affirmed", "negated", "question", "uncertain"]


class MedicationFinding(BaseModel):
    id: str
    raw_text: str  # verbatim as spoken -- never overwritten by a normalized guess
    name_candidates: list[NormalizedCandidate] = Field(default_factory=list)
    ingredient_or_brand: Literal["ingredient", "brand", "unknown"] = "unknown"
    dose_candidates: list[NormalizedCandidate] = Field(default_factory=list)
    route: Optional[str] = None
    frequency: Optional[str] = None
    timing: Optional[str] = None  # e.g. "아침", "식후" -- when taken, not how often
    action: Literal["start", "continue", "stop", "change", "unknown"] = "unknown"
    polarity: Polarity = "uncertain"
    rationale: str = ""
    needs_review: bool = True
    source_spans: list[SourceSpan] = Field(default_factory=list)


class SymptomFinding(BaseModel):
    id: str
    raw_text: str
    # Keeps a doctor's question ("다리를 끄나요?") structurally distinct from
    # the patient's own statement -- a question alone must never become an
    # affirmed symptom (see enrichment_validation.py).
    reported_by: Literal["patient", "guardian", "doctor_question", "doctor_observation"]
    polarity: Polarity = "uncertain"
    normalized_candidates: list[NormalizedCandidate] = Field(default_factory=list)
    rationale: str = ""
    needs_review: bool = True
    source_spans: list[SourceSpan] = Field(default_factory=list)


class ExamFinding(BaseModel):
    id: str
    raw_text: str
    kind: Literal["order", "observation"]  # 검사 지시 vs 실제 관찰 결과
    test_name_candidates: list[NormalizedCandidate] = Field(default_factory=list)
    score_computable: bool = False
    # Only ever populated when a score/grade actually appears verbatim in a
    # source_span quote -- "다리 들어보세요" alone must never produce an
    # mRS/NIHSS/MRC score (enrichment_validation.py enforces this).
    score_candidates: list[NormalizedCandidate] = Field(default_factory=list)
    # tasks/06_ASR_OUTPUT_VERIFICATION.md: a general numeric observation
    # (blood pressure, weight, glucose, pulse, temperature -- anything
    # measured, not a graded score like score_candidates above). Same
    # grounding rule applies: only ever populated when the number appears
    # verbatim in a source_span quote. Real-hardware measurement found
    # ASR frequently drops or garbles exactly this kind of number, so
    # enrichment_validation.py forces needs_review=True whenever this is
    # non-empty, regardless of what the provider set.
    value_candidates: list[NormalizedCandidate] = Field(default_factory=list)
    rationale: str = ""
    needs_review: bool = True
    source_spans: list[SourceSpan] = Field(default_factory=list)


class DiagnosisFinding(BaseModel):
    id: str
    raw_text: str
    # Only what the doctor actually stated -- a model-noticed pattern the
    # doctor never named goes to FollowUpQuestionSuggestion instead, never
    # here (see ClinicalEnrichment.follow_up_questions).
    kind: Literal["confirmed", "doctor_differential"]
    polarity: Polarity = "uncertain"
    normalized_candidates: list[NormalizedCandidate] = Field(default_factory=list)
    rationale: str = ""
    needs_review: bool = True
    source_spans: list[SourceSpan] = Field(default_factory=list)


class FollowUpQuestionSuggestion(BaseModel):
    """A question the model thinks the clinician should ask -- never a
    diagnosis. E.g. specific nocturnal behavior is mentioned but the doctor
    never said "RBD": this holds the suggestion to ask more, not a
    diagnosis field. Structurally separate from DiagnosisFinding so it
    cannot be confused with one downstream."""

    id: str
    trigger_text: str  # what in the transcript prompted the suggestion
    suggested_question: str
    rationale: str = ""
    needs_review: bool = True
    source_spans: list[SourceSpan] = Field(default_factory=list)


class PlanFinding(BaseModel):
    id: str
    raw_text: str
    kind: Literal["directive", "discussion"]  # 실제 지시 vs 단순 논의
    polarity: Polarity = "uncertain"
    rationale: str = ""
    needs_review: bool = True
    source_spans: list[SourceSpan] = Field(default_factory=list)


class ClinicalEnrichment(BaseModel):
    """tasks/04_CLINICAL_ENRICHMENT.md: sits between the ASR transcript and
    structure_llm (app/pipeline/enrichment.py), turning colloquial dialogue
    into clinician-reviewable candidates linked back to source text. Never
    replaces transcript_text/ClinicalStructure -- purely additive, and only
    populated when segment-level speaker/time metadata exists (audio-derived
    PipelineRuns; None for manual text-only encounters)."""

    medications: list[MedicationFinding] = Field(default_factory=list)
    symptoms: list[SymptomFinding] = Field(default_factory=list)
    exam: list[ExamFinding] = Field(default_factory=list)
    diagnoses: list[DiagnosisFinding] = Field(default_factory=list)
    follow_up_questions: list[FollowUpQuestionSuggestion] = Field(default_factory=list)
    plan: list[PlanFinding] = Field(default_factory=list)
    # Filled in by enrichment_validation.py after the LLM call, never by the
    # LLM itself -- one string per mechanically-caught safety violation
    # (ungrounded quote, ungrounded score, question-only diagnosis, etc.).
    validator_violations: list[str] = Field(default_factory=list)


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

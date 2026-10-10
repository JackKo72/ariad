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


# tasks/10_CLINICAL_FRAME_AND_REVIEW.md: slots real ICU/ER role-play evals
# showed the LLM dropping for lack of a place to put them (tasks/09).
class Decision(BaseModel):
    """A clinical decision as said, including "decided NOT to" -- e.g. "EVT
    지금은 안 함", "clopi loading 안 함" -- so a negative decision is never
    squeezed into a positive slot (medications.action=start)."""

    text: str
    status: Literal["decided_to_do", "decided_not_to_do", "conditional", "undecided"]
    condition: str = ""
    rationale: str = ""
    source_segment_ids: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False


class Finding(BaseModel):
    """tasks/13-a: a test/exam/imaging RESULT as told -- what was looked at,
    what it showed, and the doctor's own interpretation if said. `tests`
    stays the order/plan; results had no slot, so the LLM dropped them
    (ER: "굵은 혈관은 뚫려 있음", perfusion explanations)."""

    test_or_exam: str
    result: str
    interpretation: str = ""
    source_segment_ids: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False


class FamilyStatement(BaseModel):
    text: str
    speaker_role: Literal["guardian", "patient", "unknown"]
    kind: Literal["report", "question", "request"]
    source_segment_ids: list[str] = Field(default_factory=list)


class TermCandidate(BaseModel):
    """A clinical term for something said in lay words, allowed only from
    the clinician-selected clinical frame's vocabulary (prompts/frames/) and
    always routed to clinician review -- never a confirmed finding."""

    spoken_text: str
    term: str
    frame: str
    source_segment_ids: list[str] = Field(default_factory=list)
    # tasks/12: "exam" = exam/observation record (shown, no sign-off);
    # "inference" = suspected diagnosis/procedure (clinician must check).
    # Always overwritten from the frame vocabulary by
    # app/pipeline/frames.validate_term_candidates -- never trusted from the LLM.
    risk: Literal["exam", "inference"] = "inference"


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
    # tasks/10 additions -- default empty so versions stored before them
    # still load.
    treatments_given: list[PlanItem] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    consents: list[PlanItem] = Field(default_factory=list)
    disposition: list[PlanItem] = Field(default_factory=list)
    prognosis_and_goals: list[PlanItem] = Field(default_factory=list)
    family_statements: list[FamilyStatement] = Field(default_factory=list)
    term_candidates: list[TermCandidate] = Field(default_factory=list)


# One file per id in prompts/frames/ (test_clinical_frame checks they match).
class TermCandidateList(BaseModel):
    """Response of the dedicated term_candidates call (tasks/13-c)."""

    term_candidates: list[TermCandidate] = Field(default_factory=list)


ClinicalFrameId = Literal[
    "general_neuro", "stroke", "seizure", "headache", "dizziness", "movement", "cognitive", "neuromuscular", "spine",
    "icu",
]


class ReviewItem(BaseModel):
    """One thing a clinician must explicitly check before approval
    (app/pipeline/review_checklist.py). `id` is derived from the item's
    content, so editing the item invalidates an earlier acknowledgment."""

    id: str
    kind: Literal["decision", "term_candidate", "medication"]
    text: str
    source_segment_ids: list[str] = Field(default_factory=list)


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
    # tasks/10: the clinical frame the clinician selected for this run, if
    # any -- part of the reproducibility record (docs/AI_PIPELINE.md 6).
    clinical_frame: Optional[ClinicalFrameId] = None
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
    # tasks/10: computed from the current draft's structure; approval
    # requires every id to be acknowledged.
    review_checklist: list[ReviewItem] = Field(default_factory=list)


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

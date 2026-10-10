// Mirrors apps/api/app/domain/models.py. Kept in one place so every page
// imports the same shapes instead of redeclaring them (docs/ARCHITECTURE.md:
// Web talks to the API only, never to the DB/LLM directly).

export type EncounterStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "PROCESSING"
  | "REVIEW_REQUIRED"
  | "APPROVED"
  | "PUBLISHED"
  | "PROCESSING_FAILED"
  | "REVOKED";

export interface ClinicalStructure {
  problems: Array<{ text: string; certainty: string; source_segment_ids: string[] }>;
  tests: Array<Record<string, unknown>>;
  medications: Array<Record<string, unknown>>;
  plan: Array<{ text: string; source_segment_ids: string[] }>;
  warnings: Array<{ text: string; source_segment_ids: string[] }>;
  follow_up: Array<{ text: string; source_segment_ids: string[] }>;
  questions_or_conflicts: string[];
  // tasks/10 slots
  treatments_given: Array<{ text: string; source_segment_ids: string[] }>;
  findings: Array<{
    test_or_exam: string;
    result: string;
    interpretation: string;
    source_segment_ids: string[];
    needs_confirmation: boolean;
  }>;
  decisions: Decision[];
  consents: Array<{ text: string; source_segment_ids: string[] }>;
  disposition: Array<{ text: string; source_segment_ids: string[] }>;
  prognosis_and_goals: Array<{ text: string; source_segment_ids: string[] }>;
  family_statements: Array<{
    text: string;
    speaker_role: "guardian" | "patient" | "unknown";
    kind: "report" | "question" | "request";
    source_segment_ids: string[];
  }>;
  term_candidates: Array<{
    spoken_text: string;
    term: string;
    frame: string;
    source_segment_ids: string[];
    risk: "exam" | "inference";
  }>;
}

export type DecisionStatus = "decided_to_do" | "decided_not_to_do" | "conditional" | "undecided";

export interface Decision {
  text: string;
  status: DecisionStatus;
  condition: string;
  rationale: string;
  source_segment_ids: string[];
  needs_confirmation: boolean;
}

export type ClinicalFrameId =
  | "general_neuro"
  | "stroke"
  | "seizure"
  | "headache"
  | "dizziness"
  | "movement"
  | "cognitive"
  | "neuromuscular"
  | "spine"
  | "icu";

// Every frame also includes the shared neurologic-exam and ICU/medicine vocabularies.
export const CLINICAL_FRAME_LABELS: Record<ClinicalFrameId, string> = {
  general_neuro: "일반 신경과 (신경학적 진찰만)",
  stroke: "뇌졸중 (stroke)",
  seizure: "경련/발작 (seizure)",
  headache: "두통 (headache)",
  dizziness: "어지럼 (dizziness)",
  movement: "이상운동/파킨슨 (movement)",
  cognitive: "인지/치매 (cognitive)",
  neuromuscular: "신경근육 (neuromuscular)",
  spine: "척추·신경근 (spine)",
  icu: "중환자/내과 일반 (ICU)",
};

export interface ReviewItem {
  id: string;
  kind: "decision" | "term_candidate" | "medication";
  text: string;
  source_segment_ids: string[];
}

export interface ExplanationDraft {
  draft_notice: string;
  current_situation: string[];
  tests_and_reasons: string[];
  treatment_plan: string[];
  medication_instructions: string[];
  warning_signs: string[];
  what_to_do_next: string[];
  follow_up: string[];
  items_to_confirm_with_clinician: string[];
  source_map: Array<{ field: string; source_segment_ids: string[] }>;
}

export interface EncounterVersion {
  id: string;
  encounter_id: string;
  version_number: number;
  status: "draft" | "approved";
  transcript_text: string;
  structure: ClinicalStructure;
  explanation: ExplanationDraft;
  clinical_frame: ClinicalFrameId | null;
  prompt_version_structure: string | null;
  prompt_version_explanation: string | null;
  created_at: string;
  approved_at: string | null;
}

export interface Encounter {
  id: string;
  status: EncounterStatus;
  consent_confirmed: boolean;
  error_code: string | null;
  public_token: string | null;
  current_draft_version_id: string | null;
  approved_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export type SpeakerRole = "doctor" | "patient" | "guardian" | "unknown";

export interface DiarizedSegment {
  id: string;
  speaker: string;
  role: SpeakerRole;
  role_confidence: number | null;
  start: number;
  end: number;
  text: string;
}

export interface PipelineRun {
  id: string;
  encounter_id: string;
  mode: "demo" | "manual" | "provider";
  status: "needs_role_confirmation" | "completed";
  audio_asset_id: string | null;
  sample_id: string | null;
  segments: DiarizedSegment[];
  roles: Record<string, string>;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface EncounterDetail {
  encounter: Encounter;
  draft_version: EncounterVersion | null;
  approved_version: EncounterVersion | null;
  active_pipeline_run: PipelineRun | null;
  review_checklist: ReviewItem[];
}

export interface AudioAsset {
  id: string;
  encounter_id: string;
  kind: "original" | "processed";
  original_filename: string | null;
  mime_type: string | null;
  size_bytes: number;
  duration_seconds: number;
  preprocessing_mode: "none" | "light_denoise" | null;
  source_asset_id: string | null;
  sample_id: string | null;
  created_at: string;
}

export interface SampleSelectionResult {
  audio_asset: AudioAsset;
  pipeline_run: PipelineRun;
}

export interface Capabilities {
  mode: string;
  ffmpeg: boolean;
  sample_audio: boolean;
  asr: string;
  llm: string;
}

export interface ApiErrorBody {
  error_code: string;
  message: string;
  retryable: boolean;
}

export const STATUS_LABELS: Record<EncounterStatus, string> = {
  DRAFT: "작성 중",
  SUBMITTED: "제출됨",
  PROCESSING: "처리 중",
  REVIEW_REQUIRED: "검토 필요",
  APPROVED: "승인됨",
  PUBLISHED: "공개됨",
  PROCESSING_FAILED: "처리 실패",
  REVOKED: "공개 취소됨",
};

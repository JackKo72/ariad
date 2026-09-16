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

export interface EncounterDetail {
  encounter: Encounter;
  draft_version: EncounterVersion | null;
  approved_version: EncounterVersion | null;
}

export interface AudioAsset {
  id: string;
  encounter_id: string;
  kind: "original" | "processed";
  original_filename: string | null;
  mime_type: string | null;
  size_bytes: number;
  duration_seconds: number;
  created_at: string;
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

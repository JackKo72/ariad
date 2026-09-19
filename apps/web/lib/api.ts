// The only place apps/web talks HTTP to the API. Every page must go through
// this module, never fetch(DB/LLM) directly (docs/ARCHITECTURE.md Web row).

import type {
  ApiErrorBody,
  AudioAsset,
  Capabilities,
  ClinicalStructure,
  Encounter,
  EncounterDetail,
  ExplanationDraft,
  SampleSelectionResult,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  retryable: boolean;
  status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.code = body.error_code;
    this.retryable = body.retryable;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    let body: ApiErrorBody;
    try {
      body = await res.json();
    } catch {
      body = { error_code: "UNKNOWN_ERROR", message: `HTTP ${res.status}`, retryable: false };
    }
    throw new ApiError(res.status, body);
  }
  return res.json() as Promise<T>;
}

export function listEncounters(): Promise<Encounter[]> {
  return request<Encounter[]>("/encounters");
}

export function createEncounter(consentConfirmed: boolean): Promise<Encounter> {
  return request<Encounter>("/encounters", {
    method: "POST",
    body: JSON.stringify({ consent_confirmed: consentConfirmed }),
  });
}

export function getEncounter(id: string): Promise<EncounterDetail> {
  return request<EncounterDetail>(`/encounters/${id}`);
}

export function submitInput(id: string, transcriptText: string): Promise<EncounterDetail> {
  return request<EncounterDetail>(`/encounters/${id}/input`, {
    method: "POST",
    body: JSON.stringify({ transcript_text: transcriptText }),
  });
}

export function processEncounter(id: string): Promise<EncounterDetail> {
  return request<EncounterDetail>(`/encounters/${id}/process`, { method: "POST" });
}

export function updateDraft(
  id: string,
  structure: ClinicalStructure,
  explanation: ExplanationDraft,
  expectedVersionNumber: number,
): Promise<EncounterDetail> {
  return request<EncounterDetail>(`/encounters/${id}/draft`, {
    method: "PATCH",
    body: JSON.stringify({
      structure,
      explanation,
      expected_version_number: expectedVersionNumber,
    }),
  });
}

export function approveEncounter(id: string, expectedVersionNumber: number): Promise<EncounterDetail> {
  return request<EncounterDetail>(`/encounters/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ expected_version_number: expectedVersionNumber }),
  });
}

export function publishEncounter(id: string): Promise<EncounterDetail> {
  return request<EncounterDetail>(`/encounters/${id}/publish`, { method: "POST" });
}

export function revokeEncounter(id: string): Promise<EncounterDetail> {
  return request<EncounterDetail>(`/encounters/${id}/revoke`, { method: "POST" });
}

export function getPublicExplanation(token: string): Promise<ExplanationDraft> {
  return request<ExplanationDraft>(`/public/explanations/${token}`);
}

// Uses XMLHttpRequest (not fetch) because upload progress events need it.
export function uploadAudio(
  encounterId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<AudioAsset> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/encounters/${encounterId}/audio`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = { error_code: "UNKNOWN_ERROR", message: `HTTP ${xhr.status}`, retryable: false };
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as AudioAsset);
      } else {
        reject(new ApiError(xhr.status, body as ApiErrorBody));
      }
    };
    xhr.onerror = () => {
      reject(new ApiError(0, { error_code: "NETWORK_ERROR", message: "네트워크 오류로 업로드에 실패했습니다.", retryable: true }));
    };

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

export function audioStreamUrl(encounterId: string, assetId: string): string {
  return `${API_BASE_URL}/encounters/${encounterId}/audio/${assetId}/stream`;
}

export type PreprocessingMode = "none" | "light_denoise";

export function preprocessAudio(
  encounterId: string,
  sourceAssetId: string,
  mode: PreprocessingMode,
): Promise<AudioAsset> {
  return request<AudioAsset>(`/encounters/${encounterId}/audio/preprocess`, {
    method: "POST",
    body: JSON.stringify({ source_asset_id: sourceAssetId, mode }),
  });
}

export function selectSampleAudio(encounterId: string, sampleId: string): Promise<SampleSelectionResult> {
  return request<SampleSelectionResult>(`/encounters/${encounterId}/audio/sample`, {
    method: "POST",
    body: JSON.stringify({ sample_id: sampleId }),
  });
}

export function setSpeakerRoles(
  encounterId: string,
  roles: Record<string, string>,
): Promise<EncounterDetail> {
  return request<EncounterDetail>(`/encounters/${encounterId}/speaker-roles`, {
    method: "PATCH",
    body: JSON.stringify({ roles }),
  });
}

export function getCapabilities(): Promise<Capabilities> {
  return request<Capabilities>("/system/capabilities");
}

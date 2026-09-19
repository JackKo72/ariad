"use client";

import { useState } from "react";
import { ApiError, processEncounter, setSpeakerRoles } from "@/lib/api";
import type { PipelineRun, SpeakerRole } from "@/lib/types";

const ROLE_OPTIONS: Array<{ value: SpeakerRole; label: string }> = [
  { value: "doctor", label: "의사" },
  { value: "patient", label: "환자" },
  { value: "guardian", label: "보호자" },
  { value: "unknown", label: "미상" },
];

export default function SpeakerRoleConfirmation({
  encounterId,
  pipelineRun,
  onConfirmed,
}: {
  encounterId: string;
  pipelineRun: PipelineRun;
  onConfirmed: () => Promise<unknown>;
}) {
  const speakers = Array.from(new Set(pipelineRun.segments.map((s) => s.speaker))).sort();
  const [roles, setRoles] = useState<Record<string, SpeakerRole>>(() => {
    const initial: Record<string, SpeakerRole> = {};
    for (const speaker of speakers) initial[speaker] = "unknown";
    return initial;
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setLoading(true);
    setError(null);
    try {
      await setSpeakerRoles(encounterId, roles);
      await processEncounter(encounterId);
      await onConfirmed();
    } catch (err) {
      setError(err instanceof ApiError ? `[${err.code}] ${err.message}` : "역할 확인에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>화자 역할 확인</h2>
      <p style={{ fontSize: "0.85rem", color: "var(--color-muted)" }}>
        임상정보 구조화를 시작하기 전에 각 화자가 의사/환자/보호자 중 누구인지 확인해주세요.
      </p>

      {speakers.map((speaker) => {
        const example = pipelineRun.segments.find((s) => s.speaker === speaker)?.text;
        return (
          <div key={speaker} style={{ marginBottom: 12 }}>
            <label>화자 {speaker}</label>
            <select
              data-testid={`role-select-${speaker}`}
              value={roles[speaker]}
              onChange={(e) =>
                setRoles((prev) => ({ ...prev, [speaker]: e.target.value as SpeakerRole }))
              }
            >
              {ROLE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            {example && (
              <div style={{ fontSize: "0.8rem", color: "var(--color-muted)", marginTop: 4 }}>
                예: &quot;{example}&quot;
              </div>
            )}
          </div>
        );
      })}

      {error && <div className="error-box">{error}</div>}
      <div className="actions">
        <button data-testid="confirm-roles-button" disabled={loading} onClick={handleConfirm}>
          {loading ? "처리 중..." : "역할 확인 및 계속 처리"}
        </button>
      </div>
    </div>
  );
}

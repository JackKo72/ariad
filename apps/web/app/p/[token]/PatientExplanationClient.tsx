"use client";

import { useEffect, useState } from "react";
import { ApiError, getPublicExplanation } from "@/lib/api";
import type { ExplanationDraft } from "@/lib/types";

const FIELDS: Array<[keyof ExplanationDraft, string]> = [
  ["current_situation", "현재 상태"],
  ["tests_and_reasons", "검사와 이유"],
  ["treatment_plan", "치료 계획"],
  ["medication_instructions", "약물 안내"],
  ["warning_signs", "위험 신호"],
  ["what_to_do_next", "다음에 할 일"],
  ["follow_up", "다음 방문/후속조치"],
  ["items_to_confirm_with_clinician", "의료진 확인 필요 항목"],
];

export default function PatientExplanationClient({ token }: { token: string }) {
  const [explanation, setExplanation] = useState<ExplanationDraft | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPublicExplanation(token)
      .then(setExplanation)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError("설명을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
        }
      });
  }, [token]);

  if (notFound) {
    return (
      <main className="page">
        <div className="empty-state" data-testid="patient-not-found">
          <p>아직 공개된 설명이 없습니다.</p>
          <p>담당 의료진에게 확인해 주세요.</p>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="page">
        <div className="error-box">{error}</div>
      </main>
    );
  }

  if (!explanation) {
    return (
      <main className="page">
        <p>불러오는 중...</p>
      </main>
    );
  }

  return (
    <main className="page" data-testid="patient-explanation">
      <h1>진료 설명</h1>
      <p className="notice-box">{explanation.draft_notice}</p>
      {FIELDS.map(([field, label]) => {
        const items = explanation[field];
        if (!Array.isArray(items) || items.length === 0) return null;
        return (
          <div className="card" key={field}>
            <h2 style={{ marginTop: 0 }}>{label}</h2>
            <ul className="field-list">
              {items.map((item, i) => (
                <li key={i}>{item as string}</li>
              ))}
            </ul>
          </div>
        );
      })}
    </main>
  );
}

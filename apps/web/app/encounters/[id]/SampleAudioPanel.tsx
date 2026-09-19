"use client";

import { useState } from "react";
import { ApiError, selectSampleAudio } from "@/lib/api";

const SAMPLE_ID = "sample_consultation";

export default function SampleAudioPanel({
  encounterId,
  onSelected,
}: {
  encounterId: string;
  onSelected: () => Promise<unknown>;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSelect() {
    setLoading(true);
    setError(null);
    try {
      await selectSampleAudio(encounterId, SAMPLE_ID);
      await onSelected();
    } catch (err) {
      setError(err instanceof ApiError ? `[${err.code}] ${err.message}` : "샘플 선택에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <p className="notice-box" data-testid="demo-result-notice">
        합성 진료 음성 샘플입니다. 실제 환자 정보가 아니며, 전사·구조화·환자 설명은 Demo result(미리
        준비된 고정 결과)입니다.
      </p>
      {error && <div className="error-box">{error}</div>}
      <div className="actions">
        <button data-testid="select-sample-button" disabled={loading} onClick={handleSelect}>
          {loading ? "준비 중..." : "샘플로 시작"}
        </button>
      </div>
    </div>
  );
}

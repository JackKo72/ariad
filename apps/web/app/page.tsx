"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, createEncounter, listEncounters } from "@/lib/api";
import { STATUS_LABELS, type Encounter } from "@/lib/types";

export default function HomePage() {
  const router = useRouter();
  const [encounters, setEncounters] = useState<Encounter[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [consentConfirmed, setConsentConfirmed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    listEncounters()
      .then(setEncounters)
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "면담 목록을 불러오지 못했습니다.");
      });
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!consentConfirmed) return;
    setCreating(true);
    setCreateError(null);
    try {
      const encounter = await createEncounter(true);
      router.push(`/encounters/${encounter.id}`);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "면담을 생성하지 못했습니다.");
      setCreating(false);
    }
  }

  return (
    <main className="page">
      <h1>ARIAD 면담 목록</h1>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>새 면담 만들기</h2>
        <form onSubmit={handleCreate}>
          <label>
            <input
              type="checkbox"
              data-testid="consent-checkbox"
              checked={consentConfirmed}
              onChange={(e) => setConsentConfirmed(e.target.checked)}
            />{" "}
            환자(보호자)의 녹음/기록 활용 동의를 확인했습니다.
          </label>
          {createError && <div className="error-box">{createError}</div>}
          <button
            type="submit"
            data-testid="create-encounter-button"
            disabled={!consentConfirmed || creating}
            style={{ marginTop: 12 }}
          >
            {creating ? "생성 중..." : "새 면담 만들기"}
          </button>
        </form>
      </div>

      <h2>진행 중인 면담</h2>
      {loadError && <div className="error-box">{loadError}</div>}
      {!loadError && encounters === null && <p>불러오는 중...</p>}
      {encounters !== null && encounters.length === 0 && (
        <p className="empty-state">아직 생성된 면담이 없습니다.</p>
      )}
      {encounters?.map((encounter) => (
        <div className="card" key={encounter.id} data-testid="encounter-list-item">
          <Link href={`/encounters/${encounter.id}`}>
            <span className={`status-badge ${encounter.status === "PROCESSING_FAILED" ? "failed" : ""} ${encounter.status === "PUBLISHED" ? "published" : ""}`}>
              {STATUS_LABELS[encounter.status]}
            </span>
            <div style={{ marginTop: 8, fontSize: "0.85rem", color: "var(--color-muted)" }}>
              생성일: {new Date(encounter.created_at).toLocaleString("ko-KR")}
            </div>
          </Link>
        </div>
      ))}
    </main>
  );
}

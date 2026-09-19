"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  approveEncounter,
  getEncounter,
  processEncounter,
  publishEncounter,
  revokeEncounter,
  submitInput,
  updateDraft,
} from "@/lib/api";
import { STATUS_LABELS, type EncounterDetail, type ExplanationDraft } from "@/lib/types";
import { arrayToText, buildExplanationFromText, buildStructureFromText } from "@/lib/textFields";
import AudioUploadPanel from "./AudioUploadPanel";
import SampleAudioPanel from "./SampleAudioPanel";
import SpeakerRoleConfirmation from "./SpeakerRoleConfirmation";

type InputMethod = "transcript" | "audio" | "sample";

const EXPLANATION_TEXT_FIELDS = [
  ["current_situation", "현재 상태"],
  ["tests_and_reasons", "검사와 이유"],
  ["treatment_plan", "치료 계획"],
  ["medication_instructions", "약물 안내"],
  ["warning_signs", "위험 신호"],
  ["what_to_do_next", "다음에 할 일"],
  ["follow_up", "다음 방문/후속조치"],
  ["items_to_confirm_with_clinician", "의료진 확인 필요 항목"],
] as const;

export default function EncounterDetailClient({ id }: { id: string }) {
  const [detail, setDetail] = useState<EncounterDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const [inputMethod, setInputMethod] = useState<InputMethod>("transcript");
  const [transcriptInput, setTranscriptInput] = useState("");
  const [problemsText, setProblemsText] = useState("");
  const [draftNotice, setDraftNotice] = useState("");
  const [fieldTexts, setFieldTexts] = useState<Record<string, string>>({});

  const reload = useCallback(() => {
    setLoadError(null);
    return getEncounter(id)
      .then((d) => {
        setDetail(d);
        return d;
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "면담 정보를 불러오지 못했습니다.");
        return null;
      });
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    getEncounter(id)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(err instanceof ApiError ? err.message : "면담 정보를 불러오지 못했습니다.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Editable text state is derived from the loaded version but must stay
  // locally editable. Resetting it during render instead of in an effect
  // avoids an extra render pass -- see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  //
  // The sync key includes status, not just version id: the pipeline (and a
  // save while still REVIEW_REQUIRED) mutate the *same* draft row's content
  // in place, so id alone would miss the PROCESSING -> REVIEW_REQUIRED
  // transition that first populates the mock structure/explanation.
  const editableVersionForSync = detail?.draft_version ?? detail?.approved_version ?? null;
  const syncKey = editableVersionForSync ? `${editableVersionForSync.id}#${detail?.encounter.status}` : null;
  const [syncedKey, setSyncedKey] = useState<string | null>(null);
  if (editableVersionForSync && syncKey !== syncedKey) {
    setSyncedKey(syncKey);
    setProblemsText(arrayToText(editableVersionForSync.structure.problems.map((p) => p.text)));
    setDraftNotice(editableVersionForSync.explanation.draft_notice);
    const next: Record<string, string> = {};
    for (const [field] of EXPLANATION_TEXT_FIELDS) {
      next[field] = arrayToText(
        (editableVersionForSync.explanation as unknown as Record<string, string[]>)[field],
      );
    }
    setFieldTexts(next);
  }

  async function runAction<T>(action: () => Promise<T>) {
    setActionLoading(true);
    setActionError(null);
    try {
      await action();
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? `[${err.code}] ${err.message}` : "요청을 처리하지 못했습니다.");
    } finally {
      setActionLoading(false);
    }
  }

  if (loadError) {
    return (
      <main className="page">
        <div className="error-box">{loadError}</div>
        <button onClick={() => reload()}>다시 시도</button>
      </main>
    );
  }

  if (!detail) {
    return (
      <main className="page">
        <p>불러오는 중...</p>
      </main>
    );
  }

  const { encounter, draft_version, approved_version } = detail;
  const editableVersion = draft_version ?? approved_version;

  return (
    <main className="page">
      <Link href="/">← 목록으로</Link>
      <h1>면담 상세</h1>
      <span
        data-testid="status-badge"
        data-status={encounter.status}
        className={`status-badge ${encounter.status === "PROCESSING_FAILED" ? "failed" : ""} ${encounter.status === "PUBLISHED" ? "published" : ""}`}
      >
        {STATUS_LABELS[encounter.status]}
      </span>

      {actionError && <div className="error-box">{actionError}</div>}

      {encounter.status === "DRAFT" && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>입력 방법 선택</h2>
          <div className="actions" style={{ marginTop: 0, marginBottom: 12 }}>
            <button
              data-testid="input-method-sample"
              className={inputMethod === "sample" ? "" : "secondary"}
              onClick={() => setInputMethod("sample")}
            >
              샘플 음성 사용
            </button>
            <button
              data-testid="input-method-audio"
              className={inputMethod === "audio" ? "" : "secondary"}
              onClick={() => setInputMethod("audio")}
            >
              내 컴퓨터에서 음성파일 선택
            </button>
            <button
              data-testid="input-method-transcript"
              className={inputMethod === "transcript" ? "" : "secondary"}
              onClick={() => setInputMethod("transcript")}
            >
              전사문 직접 입력
            </button>
          </div>

          {inputMethod === "sample" && <SampleAudioPanel encounterId={id} onSelected={reload} />}

          {inputMethod === "transcript" && (
            <>
              <textarea
                data-testid="transcript-input"
                rows={8}
                placeholder={"의사: ...\n환자: ..."}
                value={transcriptInput}
                onChange={(e) => setTranscriptInput(e.target.value)}
              />
              <div className="actions">
                <button
                  data-testid="submit-input-button"
                  disabled={actionLoading || transcriptInput.trim().length === 0}
                  onClick={() => runAction(() => submitInput(id, transcriptInput))}
                >
                  제출
                </button>
              </div>
            </>
          )}

          {inputMethod === "audio" && <AudioUploadPanel encounterId={id} />}
        </div>
      )}

      {encounter.status === "SUBMITTED" && (
        <div className="card">
          {detail.active_pipeline_run && detail.active_pipeline_run.status === "needs_role_confirmation" ? (
            <SpeakerRoleConfirmation
              encounterId={id}
              pipelineRun={detail.active_pipeline_run}
              onConfirmed={reload}
            />
          ) : (
            <>
              <p>전사문이 제출되었습니다. 처리를 시작하세요.</p>
              <div className="actions">
                <button
                  data-testid="process-button"
                  disabled={actionLoading}
                  onClick={() => runAction(() => processEncounter(id))}
                >
                  {actionLoading ? "처리 중..." : "처리 시작"}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {encounter.status === "PROCESSING" && (
        <div className="card">
          <p>처리 중입니다...</p>
        </div>
      )}

      {encounter.status === "PROCESSING_FAILED" && (
        <div className="card">
          <div className="error-box">처리 실패: {encounter.error_code ?? "알 수 없는 오류"}</div>
          <div className="actions">
            <button disabled={actionLoading} onClick={() => runAction(() => processEncounter(id))}>
              다시 처리하기
            </button>
          </div>
        </div>
      )}

      {(encounter.status === "REVIEW_REQUIRED" || encounter.status === "APPROVED") && editableVersion && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>
            {encounter.status === "APPROVED" ? "승인된 내용 (수정 시 새 draft 생성)" : "검토 및 수정"}
          </h2>
          <details>
            <summary>원본 전사문 보기</summary>
            <pre style={{ whiteSpace: "pre-wrap" }}>{editableVersion.transcript_text}</pre>
          </details>

          <label>구조화된 임상 사실 (한 줄에 하나)</label>
          <textarea
            data-testid="problems-input"
            rows={4}
            value={problemsText}
            onChange={(e) => setProblemsText(e.target.value)}
          />

          <label>환자용 설명 안내문</label>
          <input type="text" value={draftNotice} onChange={(e) => setDraftNotice(e.target.value)} />

          {EXPLANATION_TEXT_FIELDS.map(([field, label]) => (
            <div key={field}>
              <label>{label} (한 줄에 하나)</label>
              <textarea
                data-testid={`field-${field}`}
                rows={3}
                value={fieldTexts[field] ?? ""}
                onChange={(e) => setFieldTexts((prev) => ({ ...prev, [field]: e.target.value }))}
              />
            </div>
          ))}

          <div className="actions">
            <button
              className="secondary"
              data-testid="save-draft-button"
              disabled={actionLoading}
              onClick={() =>
                runAction(() =>
                  updateDraft(
                    id,
                    buildStructureFromText(editableVersion.structure, problemsText),
                    buildExplanationFromText(editableVersion.explanation, draftNotice, fieldTexts),
                    editableVersion.version_number,
                  ),
                )
              }
            >
              임시 저장
            </button>
            {encounter.status === "REVIEW_REQUIRED" && (
              <button
                data-testid="approve-button"
                disabled={actionLoading}
                onClick={() =>
                  runAction(async () => {
                    await updateDraft(
                      id,
                      buildStructureFromText(editableVersion.structure, problemsText),
                      buildExplanationFromText(editableVersion.explanation, draftNotice, fieldTexts),
                      editableVersion.version_number,
                    );
                    const latest = await getEncounter(id);
                    const latestDraft = latest.draft_version;
                    if (latestDraft) {
                      await approveEncounter(id, latestDraft.version_number);
                    }
                  })
                }
              >
                승인
              </button>
            )}
          </div>
        </div>
      )}

      {encounter.status === "APPROVED" && (
        <div className="card">
          <div className="actions">
            <button
              data-testid="publish-button"
              disabled={actionLoading}
              onClick={() => runAction(() => publishEncounter(id))}
            >
              환자에게 공개하기
            </button>
          </div>
        </div>
      )}

      {encounter.status === "PUBLISHED" && (
        <div className="card">
          <p>환자용 페이지가 공개되었습니다.</p>
          <a
            className="public-link"
            data-testid="public-link"
            href={`/p/${encounter.public_token}`}
            target="_blank"
            rel="noreferrer"
          >
            {typeof window !== "undefined" ? window.location.origin : ""}/p/{encounter.public_token}
          </a>
          {approved_version && (
            <div style={{ marginTop: 16 }}>
              <h2>승인된 환자 설명 미리보기</h2>
              <ExplanationPreview explanation={approved_version.explanation} />
            </div>
          )}
          <div className="actions">
            <button
              className="danger"
              data-testid="revoke-button"
              disabled={actionLoading}
              onClick={() => runAction(() => revokeEncounter(id))}
            >
              공개 취소
            </button>
          </div>
        </div>
      )}

      {encounter.status === "REVOKED" && (
        <div className="card">
          <p>이 면담의 공개가 취소되었습니다.</p>
        </div>
      )}
    </main>
  );
}

function ExplanationPreview({ explanation }: { explanation: ExplanationDraft }) {
  return (
    <div>
      <p className="notice-box">{explanation.draft_notice}</p>
      {EXPLANATION_TEXT_FIELDS.map(([field, label]) => {
        const items = (explanation as unknown as Record<string, string[]>)[field];
        if (!items || items.length === 0) return null;
        return (
          <div key={field}>
            <strong>{label}</strong>
            <ul className="field-list">
              {items.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

"use client";

import { useState } from "react";
import { ApiError, audioStreamUrl, preprocessAudio, uploadAudio, type PreprocessingMode } from "@/lib/api";
import type { AudioAsset } from "@/lib/types";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

export default function AudioUploadPanel({ encounterId }: { encounterId: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [asset, setAsset] = useState<AudioAsset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const [preprocessingMode, setPreprocessingMode] = useState<PreprocessingMode>("none");
  const [processedAsset, setProcessedAsset] = useState<AudioAsset | null>(null);
  const [preprocessing, setPreprocessing] = useState(false);
  const [preprocessError, setPreprocessError] = useState<string | null>(null);

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0];
    if (!selected) return;
    setFile(selected);
    setAsset(null);
    setProcessedAsset(null);
    setError(null);
    setUploading(true);
    setProgress(0);
    try {
      const uploaded = await uploadAudio(encounterId, selected, setProgress);
      setAsset(uploaded);
    } catch (err) {
      setError(err instanceof ApiError ? `[${err.code}] ${err.message}` : "업로드에 실패했습니다.");
    } finally {
      setUploading(false);
    }
  }

  async function handlePreprocess() {
    if (!asset) return;
    setPreprocessing(true);
    setPreprocessError(null);
    try {
      const processed = await preprocessAudio(encounterId, asset.id, preprocessingMode);
      setProcessedAsset(processed);
    } catch (err) {
      setPreprocessError(err instanceof ApiError ? `[${err.code}] ${err.message}` : "전처리에 실패했습니다.");
    } finally {
      setPreprocessing(false);
    }
  }

  return (
    <div>
      <input
        type="file"
        data-testid="audio-file-input"
        accept=".mp3,.mp4,.mpeg,.mpga,.m4a,.wav,.webm,audio/*"
        onChange={handleFileChange}
        disabled={uploading}
      />

      {file && (
        <div style={{ fontSize: "0.85rem", marginTop: 8, color: "var(--color-muted)" }}>
          <div>파일명: {file.name}</div>
          <div>형식(브라우저 감지): {file.type || "알 수 없음"}</div>
          <div>크기: {formatBytes(file.size)}</div>
        </div>
      )}

      {uploading && (
        <div data-testid="upload-progress" style={{ marginTop: 8 }}>
          업로드 중... {progress ?? 0}%
        </div>
      )}

      {error && <div className="error-box">{error}</div>}

      {asset && (
        <div style={{ marginTop: 12 }} data-testid="audio-asset-info">
          <label>원본 (서버 확인 길이: {formatDuration(asset.duration_seconds)})</label>
          <audio
            controls
            data-testid="original-audio-player"
            src={audioStreamUrl(encounterId, asset.id)}
            style={{ width: "100%" }}
          />

          <label style={{ marginTop: 16 }}>전처리 방식</label>
          <div className="actions" style={{ marginTop: 0 }}>
            <button
              data-testid="preprocess-mode-none"
              className={preprocessingMode === "none" ? "" : "secondary"}
              onClick={() => setPreprocessingMode("none")}
            >
              원본 유지 (표준화만)
            </button>
            <button
              data-testid="preprocess-mode-light-denoise"
              className={preprocessingMode === "light_denoise" ? "" : "secondary"}
              onClick={() => setPreprocessingMode("light_denoise")}
            >
              가벼운 소음처리
            </button>
          </div>
          <div className="actions">
            <button
              data-testid="preprocess-button"
              disabled={preprocessing}
              onClick={handlePreprocess}
            >
              {preprocessing ? "전처리 중..." : "전처리 시작"}
            </button>
          </div>

          {preprocessError && <div className="error-box">{preprocessError}</div>}

          {processedAsset && (
            <div style={{ marginTop: 12 }} data-testid="processed-audio-info">
              <label>
                전처리 결과 ({processedAsset.preprocessing_mode === "light_denoise" ? "가벼운 소음처리" : "원본 유지"},
                길이: {formatDuration(processedAsset.duration_seconds)})
              </label>
              <audio
                controls
                data-testid="processed-audio-player"
                src={audioStreamUrl(encounterId, processedAsset.id)}
                style={{ width: "100%" }}
              />
              <p className="notice-box" style={{ marginTop: 12 }}>
                원본과 전처리 결과를 번갈아 들어보고 비교할 수 있습니다. 전사 연결은 다음 단계에서
                제공됩니다. 지금은 &quot;전사문 직접 입력&quot; 탭으로 전환해 계속 진행할 수 있습니다.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

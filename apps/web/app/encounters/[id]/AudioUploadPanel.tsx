"use client";

import { useState } from "react";
import { ApiError, audioStreamUrl, uploadAudio } from "@/lib/api";
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

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0];
    if (!selected) return;
    setFile(selected);
    setAsset(null);
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
          <div style={{ fontSize: "0.85rem", color: "var(--color-muted)" }}>
            서버 확인 길이: {formatDuration(asset.duration_seconds)}
          </div>
          <audio
            controls
            data-testid="original-audio-player"
            src={audioStreamUrl(encounterId, asset.id)}
            style={{ width: "100%", marginTop: 8 }}
          />
          <p className="notice-box" style={{ marginTop: 12 }}>
            업로드가 완료되었습니다. 오디오 표준화·전사 단계는 다음 단계에서 제공됩니다. 지금은
            &quot;전사문 직접 입력&quot; 탭으로 전환해 계속 진행할 수 있습니다.
          </p>
        </div>
      )}
    </div>
  );
}

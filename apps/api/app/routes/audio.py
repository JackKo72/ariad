"""Audio upload + playback routes (tasks/02_AUDIO_PIPELINE.md Phase A).

Upload validates with ffprobe against the actual file content -- never the
claimed filename/extension/Content-Type -- before anything is persisted.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, UploadFile
from fastapi.responses import Response

from app.audio import storage, validation
from app.domain.errors import AudioFileTooLarge, NotFoundError
from app.domain.models import AudioAsset
from app.repositories.sqlite_repo import EncounterRepository

from app.dependencies import get_audio_dir, get_repository

router = APIRouter(prefix="/encounters", tags=["audio"])

_MIME_BY_FORMAT_TOKEN = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "mpga": "audio/mpeg",
    "mp4": "audio/mp4",
    "m4a": "audio/mp4",
    "webm": "audio/webm",
    "matroska": "audio/webm",
    "ogg": "audio/ogg",
}
_MIME_BY_CODEC = {
    "aac": "audio/mp4",
    "opus": "audio/webm",
    "vorbis": "audio/ogg",
    "mp3": "audio/mpeg",
    "pcm_s16le": "audio/wav",
    "pcm_s24le": "audio/wav",
    "pcm_f32le": "audio/wav",
    "wmav2": "audio/x-ms-wma",
}


def _detected_mime_type(probe: validation.AudioProbeResult) -> str:
    for token in probe.format_tokens:
        if token in _MIME_BY_FORMAT_TOKEN:
            return _MIME_BY_FORMAT_TOKEN[token]
    return _MIME_BY_CODEC.get(probe.codec_name, "application/octet-stream")


@router.post("/{encounter_id}/audio", response_model=AudioAsset, status_code=201)
async def upload_audio(
    encounter_id: str,
    file: UploadFile,
    repo: EncounterRepository = Depends(get_repository),
) -> AudioAsset:
    chunk_size = 1024 * 1024
    data = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > storage.MAX_FILE_SIZE_BYTES:
            raise AudioFileTooLarge(storage.MAX_FILE_SIZE_BYTES)
    content = bytes(data)

    audio_dir = get_audio_dir()
    asset_id, path, sha256_hash = storage.save_upload(audio_dir, encounter_id, content)

    try:
        probe = validation.probe_audio(str(path))
        validation.validate_probe_result(probe)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    return repo.create_audio_asset(
        encounter_id,
        kind="original",
        storage_path=str(path),
        original_filename=file.filename,
        mime_type=_detected_mime_type(probe),
        size_bytes=len(content),
        duration_seconds=probe.duration_seconds,
        sha256_hash=sha256_hash,
    )


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


@router.get("/{encounter_id}/audio/{artifact}/stream")
def stream_audio(
    encounter_id: str,
    artifact: str,
    repo: EncounterRepository = Depends(get_repository),
    range_header: Optional[str] = Header(default=None, alias="Range"),
) -> Response:
    asset = repo.get_audio_asset(artifact)
    if asset.encounter_id != encounter_id:
        raise NotFoundError("AudioAsset")
    storage_path = Path(repo.get_audio_asset_storage_path(artifact))
    file_size = storage_path.stat().st_size
    mime_type = asset.mime_type or "application/octet-stream"

    start, end = 0, file_size - 1
    status_code = 200
    match = _RANGE_RE.match(range_header) if range_header else None
    if match:
        start_str, end_str = match.groups()
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        end = min(end, file_size - 1)
        status_code = 206

    with open(storage_path, "rb") as f:
        f.seek(start)
        body = f.read(end - start + 1)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(len(body)),
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    return Response(content=body, status_code=status_code, media_type=mime_type, headers=headers)

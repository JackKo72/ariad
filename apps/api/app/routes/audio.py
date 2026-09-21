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
from pydantic import BaseModel

from app.audio import preprocess, storage, validation
from app.domain.errors import AsrNotConfigured, AudioFileTooLarge, NotFoundError
from app.domain.models import AudioAsset, PipelineRun, SampleSelectionResult
from app.providers.demo_asr import SAMPLE_FIXTURES_DIR, sample_is_available
from app.repositories.sqlite_repo import EncounterRepository

from app.dependencies import get_asr_provider, get_audio_dir, get_repository

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


class SampleSelectionRequest(BaseModel):
    sample_id: str


def _start_pipeline_run_for_asset(
    repo: EncounterRepository, encounter_id: str, audio_asset: AudioAsset
) -> PipelineRun:
    """Runs ASR/diarization for one asset and advances the encounter to
    SUBMITTED (placeholder transcript, filled in once roles are confirmed)
    exactly like the manual-transcript path does -- one shared continuation
    for demo, manual-upload, and (Phase D) real-provider audio alike.
    Raises AsrNotConfigured (422) when no provider is available for this
    asset -- see app.dependencies.get_asr_provider."""
    asr_provider = get_asr_provider(audio_asset)
    storage_path = repo.get_audio_asset_storage_path(audio_asset.id)
    segments = asr_provider.transcribe(audio_asset, storage_path)

    mode = "demo" if audio_asset.sample_id else "manual"
    pipeline_run = repo.create_pipeline_run(
        encounter_id,
        mode=mode,
        audio_asset_id=audio_asset.id,
        sample_id=audio_asset.sample_id,
        segments=segments,
    )
    repo.submit_input(encounter_id, "")
    return pipeline_run


@router.post("/{encounter_id}/audio/sample", response_model=SampleSelectionResult, status_code=201)
def select_sample_audio(
    encounter_id: str,
    body: SampleSelectionRequest,
    repo: EncounterRepository = Depends(get_repository),
) -> SampleSelectionResult:
    """Demo mode entry point (tasks/02_AUDIO_PIPELINE.md section 3.1): copies
    the built-in synthetic fixture into place, then runs the same
    ASR-start continuation an arbitrary upload would (see
    _start_pipeline_run_for_asset), so review/approve/publish afterwards is
    one shared code path regardless of how the transcript originated."""
    if not sample_is_available(body.sample_id):
        raise AsrNotConfigured()

    sample_wav = SAMPLE_FIXTURES_DIR / f"{body.sample_id}.wav"
    audio_dir = get_audio_dir()
    asset_id, path = storage.new_asset_path(audio_dir, encounter_id)
    path.write_bytes(sample_wav.read_bytes())
    probe = validation.probe_audio(str(path))

    audio_asset = repo.create_audio_asset(
        encounter_id,
        kind="original",
        storage_path=str(path),
        original_filename=sample_wav.name,
        mime_type=_detected_mime_type(probe),
        size_bytes=path.stat().st_size,
        duration_seconds=probe.duration_seconds,
        sha256_hash=storage.sha256_of_file(path),
        sample_id=body.sample_id,
    )

    pipeline_run = _start_pipeline_run_for_asset(repo, encounter_id, audio_asset)
    return SampleSelectionResult(audio_asset=audio_asset, pipeline_run=pipeline_run)


@router.post("/{encounter_id}/audio/{asset_id}/transcribe", response_model=PipelineRun, status_code=201)
def transcribe_audio(
    encounter_id: str,
    asset_id: str,
    repo: EncounterRepository = Depends(get_repository),
) -> PipelineRun:
    """Attempts ASR on an arbitrarily-uploaded (non-sample) asset. With no
    real ASR provider configured this always raises AsrNotConfigured (422,
    "ASR provider가 설정되지 않았습니다") -- see docs section 3.2: the
    clinician sees that message and can switch to typing the transcript
    manually instead of a blank screen."""
    asset = repo.get_audio_asset(asset_id)
    if asset.encounter_id != encounter_id:
        raise NotFoundError("AudioAsset")
    return _start_pipeline_run_for_asset(repo, encounter_id, asset)


class PreprocessRequest(BaseModel):
    source_asset_id: str
    mode: preprocess.PreprocessingMode


@router.post("/{encounter_id}/audio/preprocess", response_model=AudioAsset, status_code=201)
def preprocess_audio(
    encounter_id: str,
    body: PreprocessRequest,
    repo: EncounterRepository = Depends(get_repository),
) -> AudioAsset:
    source = repo.get_audio_asset(body.source_asset_id)
    if source.encounter_id != encounter_id or source.kind != "original":
        raise NotFoundError("AudioAsset")
    source_path = Path(repo.get_audio_asset_storage_path(body.source_asset_id))

    audio_dir = get_audio_dir()
    asset_id, output_path = storage.new_asset_path(audio_dir, encounter_id)
    preprocess.standardize_audio(source_path, output_path, body.mode)

    probe = validation.probe_audio(str(output_path))
    return repo.create_audio_asset(
        encounter_id,
        kind="processed",
        storage_path=str(output_path),
        original_filename=source.original_filename,
        mime_type="audio/wav",
        size_bytes=output_path.stat().st_size,
        duration_seconds=probe.duration_seconds,
        sha256_hash=storage.sha256_of_file(output_path),
        preprocessing_mode=body.mode,
        source_asset_id=body.source_asset_id,
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

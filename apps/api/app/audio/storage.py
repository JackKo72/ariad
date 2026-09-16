"""Server-generated audio asset storage (tasks/02_AUDIO_PIPELINE.md sections
5, 11). The uploaded filename is never used to build a path -- it is stored
only as a display-only DB field -- so path traversal and executable file
names cannot escape the audio directory. Files are stored without an
extension; ffprobe identifies the real format from content, not from name.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.domain.errors import AudioFileTooLarge
from app.ids import new_id

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024


def get_audio_root(audio_dir: str) -> Path:
    root = Path(audio_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_upload(audio_dir: str, encounter_id: str, file_bytes: bytes) -> tuple[str, Path, str]:
    """Persists file_bytes under a server-generated path.

    Returns (asset_id, path, sha256_hash). Raises AudioFileTooLarge if the
    content exceeds the 25 MB limit.
    """
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise AudioFileTooLarge(MAX_FILE_SIZE_BYTES)

    asset_id = new_id()
    encounter_dir = get_audio_root(audio_dir) / encounter_id
    encounter_dir.mkdir(parents=True, exist_ok=True)
    path = encounter_dir / asset_id
    path.write_bytes(file_bytes)
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()
    return asset_id, path, sha256_hash

"""Unit: server-generated storage path + size limit (tasks/02_AUDIO_PIPELINE.md
sections 5, 11)."""

import hashlib

import pytest

from app.audio import storage
from app.domain.errors import AudioFileTooLarge


def test_save_upload_never_uses_the_original_filename_in_the_path(tmp_path):
    asset_id, path, _ = storage.save_upload(str(tmp_path), "enc-1", b"hello world")
    assert "hello" not in str(path)
    assert asset_id in str(path)
    assert str(path).startswith(str(tmp_path))


def test_save_upload_computes_matching_sha256(tmp_path):
    content = b"synthetic audio bytes"
    _, path, sha256_hash = storage.save_upload(str(tmp_path), "enc-1", content)
    assert sha256_hash == hashlib.sha256(content).hexdigest()
    assert path.read_bytes() == content


def test_save_upload_rejects_oversized_content(tmp_path):
    oversized = b"0" * (storage.MAX_FILE_SIZE_BYTES + 1)
    with pytest.raises(AudioFileTooLarge):
        storage.save_upload(str(tmp_path), "enc-1", oversized)

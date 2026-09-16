"""Generates tiny real media files with ffmpeg for audio validation tests.

Not committed as binary fixtures -- generated on the fly so the repo stays
free of binary blobs until tests/fixtures/audio/* (Phase C) actually needs a
checked-in sample.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def make_silence_wav(path: Path, duration_seconds: float = 1.0) -> Path:
    # -f wav forces the WAV muxer regardless of the output path's extension,
    # so callers can deliberately save real WAV bytes under a misleading name.
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", str(duration_seconds), "-f", "wav", str(path),
        ],
        capture_output=True,
        check=True,
    )
    return path


def make_video_only_mp4(path: Path, duration_seconds: float = 1.0) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=64x64:duration={duration_seconds}",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True,
        check=True,
    )
    return path

"""FFmpeg standardization + optional light denoise
(tasks/02_AUDIO_PIPELINE.md section 6).

Only two denoise modes exist: "none" and "light_denoise". Both always
standardize to mono/16kHz/16-bit PCM WAV with clipping-avoiding loudness
normalization first. "light_denoise" additionally runs exactly one
conservative stationary-noise filter -- never chained/aggressive denoisers,
never a high-pass filter, per the task's explicit ban (preserving small
medication-dose numbers over a "cleaner sounding" recording).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Literal

from app.domain.errors import AudioConversionFailed

logger = logging.getLogger("ariad.audio")

PreprocessingMode = Literal["none", "light_denoise"]

_LOUDNESS_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"
_LIGHT_DENOISE_FILTER = "afftdn=nr=12:nf=-25"


def _audio_filters(mode: PreprocessingMode) -> str:
    if mode == "light_denoise":
        return f"{_LIGHT_DENOISE_FILTER},{_LOUDNESS_FILTER}"
    return _LOUDNESS_FILTER


def standardize_audio(input_path: Path, output_path: Path, mode: PreprocessingMode) -> None:
    """Writes a mono/16kHz/16-bit PCM WAV to output_path. Never touches
    input_path (docs/AI_PIPELINE.md: 원본을 덮어쓰지 않고 processed artifact를
    별도로 만든다)."""
    command = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-ac", "1",
        "-ar", "16000",
        "-sample_fmt", "s16",
        "-af", _audio_filters(mode),
        "-f", "wav",
        str(output_path),
    ]
    try:
        proc = subprocess.run(command, capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("ffmpeg standardize failed to run: %s", exc)
        raise AudioConversionFailed() from exc

    if proc.returncode != 0 or not output_path.exists():
        logger.warning(
            "ffmpeg standardize exited %s: %s", proc.returncode, proc.stderr.decode(errors="replace")[:500]
        )
        raise AudioConversionFailed()

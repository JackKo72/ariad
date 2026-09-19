"""ffprobe-based upload validation (tasks/02_AUDIO_PIPELINE.md section 5).

Never trusts the filename or its extension: every uploaded file is probed
with ffprobe to find its actual audio stream, codec, and duration. A file
that fails to probe at all (corrupt data, an executable renamed to .wav,
path-traversal-style names) is rejected before it is ever treated as media.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from app.domain.errors import (
    AudioDurationTooLong,
    AudioProbeFailed,
    AudioStreamMissing,
    AudioUnsupportedFormat,
)

MAX_DURATION_MINUTES = 30

# ffprobe's format_name is a comma-separated list of aliases (e.g. MP4/M4A
# both report "mov,mp4,m4a,3gp,3g2,mj2"), so membership is checked against
# the whole token set, not an exact match.
ALLOWED_FORMAT_TOKENS = {"wav", "mp3", "mp4", "m4a", "mpeg", "mpga", "webm", "matroska", "ogg"}
ALLOWED_CODECS = {"mp3", "aac", "pcm_s16le", "pcm_s24le", "pcm_f32le", "opus", "vorbis", "wmav2"}


@dataclass(frozen=True)
class AudioProbeResult:
    duration_seconds: float
    format_tokens: frozenset[str]
    codec_name: str


def ensure_ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _to_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _duration_from_ts(stream: dict) -> float:
    duration_ts = _to_float(stream.get("duration_ts"))
    time_base = stream.get("time_base") or ""
    if duration_ts <= 0 or "/" not in time_base:
        return 0.0
    num_str, _, den_str = time_base.partition("/")
    num, den = _to_float(num_str), _to_float(den_str)
    if den <= 0:
        return 0.0
    return duration_ts * (num / den)


def probe_audio(file_path: str) -> AudioProbeResult:
    """Runs ffprobe against the file already saved on disk."""
    if not ensure_ffprobe_available():
        raise AudioProbeFailed()

    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path,
            ],
            capture_output=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise AudioProbeFailed() from exc

    if proc.returncode != 0:
        raise AudioProbeFailed()

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AudioProbeFailed() from exc

    streams = data.get("streams", [])
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    format_info = data.get("format", {})
    format_tokens = frozenset(
        token.strip() for token in (format_info.get("format_name") or "").split(",") if token.strip()
    )

    if not audio_streams:
        raise AudioStreamMissing()

    # format.duration is missing on some real-world M4A/fragmented-MP4
    # encoders (voice memo / messaging apps in particular) even though the
    # file is perfectly valid -- fall back to the audio stream's own
    # duration, then to duration_ts/time_base, before giving up.
    duration_seconds = _to_float(format_info.get("duration"))
    if duration_seconds <= 0:
        duration_seconds = _to_float(audio_streams[0].get("duration"))
    if duration_seconds <= 0:
        duration_seconds = _duration_from_ts(audio_streams[0])

    if duration_seconds <= 0:
        raise AudioStreamMissing()

    return AudioProbeResult(
        duration_seconds=duration_seconds,
        format_tokens=format_tokens,
        codec_name=audio_streams[0].get("codec_name", ""),
    )


def validate_probe_result(probe: AudioProbeResult) -> None:
    format_ok = bool(probe.format_tokens & ALLOWED_FORMAT_TOKENS)
    codec_ok = probe.codec_name in ALLOWED_CODECS
    if not format_ok and not codec_ok:
        detected = probe.codec_name or ",".join(sorted(probe.format_tokens)) or None
        raise AudioUnsupportedFormat(detected)
    if probe.duration_seconds > MAX_DURATION_MINUTES * 60:
        raise AudioDurationTooLong(MAX_DURATION_MINUTES)

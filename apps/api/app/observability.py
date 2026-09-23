"""Stage-level latency instrumentation (tasks/03_SPEAKER_MERGE_AND_LATENCY.md
Phase 1).

A StageTimer collects one StageRecord per measured block for one request.
Each record holds only the fields docs/DEBUGGING.md's structured-log
allowlist covers (duration, status, provider/model/version, token counts,
cache_hit, error_code) -- never audio, transcript, or explanation content.
Pure/in-memory; persisting records is the caller's job (see
EncounterRepository.record_stage_runs).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional


@dataclass
class StageRecord:
    stage: str
    duration_ms: float
    status: str = "ok"
    error_code: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    schema_version: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_hit: Optional[bool] = None
    audio_duration_seconds: Optional[float] = None
    file_size_bytes: Optional[int] = None
    retry_count: int = 0


class StageTimer:
    """Usage:

        timer = StageTimer()
        with timer.stage("asr_total", provider="sherpa_onnx") as meta:
            segments = asr_provider.transcribe(...)
            meta["audio_duration_seconds"] = audio_asset.duration_seconds

    `fixed` kwargs are set once when entering; the yielded `meta` dict lets
    the caller add fields only known after the block runs (e.g. token
    counts). An exception inside the block is recorded as status="error"
    with error_code taken from the exception's own `.code` when it has one
    (AriadError subclasses) or its class name otherwise, then re-raised
    unchanged -- this never swallows the real failure.
    """

    def __init__(self) -> None:
        self.records: list[StageRecord] = []

    @contextmanager
    def stage(self, name: str, **fixed: Any) -> Iterator[dict[str, Any]]:
        meta: dict[str, Any] = {}
        start = time.perf_counter()
        status = "ok"
        error_code = None
        try:
            yield meta
        except Exception as exc:
            status = "error"
            error_code = getattr(exc, "code", type(exc).__name__)
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.records.append(
                StageRecord(
                    stage=name,
                    duration_ms=duration_ms,
                    status=status,
                    error_code=error_code,
                    **{**fixed, **meta},
                )
            )

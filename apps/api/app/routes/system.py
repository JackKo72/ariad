"""System capability introspection (tasks/02_AUDIO_PIPELINE.md section 10).

Never returns key material -- only booleans/enum strings describing what
this backend instance can currently do, so the frontend can show accurate
"no ASR configured" messaging instead of guessing from a failed request.
"""

from __future__ import annotations

import os
import shutil

from fastapi import APIRouter
from pydantic import BaseModel

from app.providers.demo_asr import sample_is_available

router = APIRouter(prefix="/system", tags=["system"])


class Capabilities(BaseModel):
    mode: str
    ffmpeg: bool
    sample_audio: bool
    asr: str  # "demo" | "openai" | "unavailable"
    llm: str  # "mock" | "openai"


@router.get("/capabilities", response_model=Capabilities)
def get_capabilities() -> Capabilities:
    mode = os.environ.get("ARIAD_MODE", "demo")
    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))

    if mode == "provider" and has_openai_key:
        asr = "openai"
    elif mode == "provider":
        asr = "unavailable"  # arbitrary uploads have no provider; the built-in sample still works via demo
    else:
        asr = "demo"

    return Capabilities(
        mode=mode,
        ffmpeg=shutil.which("ffmpeg") is not None,
        sample_audio=sample_is_available("sample_consultation"),
        asr=asr,
        llm="openai" if (mode == "provider" and has_openai_key) else "mock",
    )

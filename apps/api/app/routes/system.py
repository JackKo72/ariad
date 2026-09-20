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
    asr: str  # "demo" | "local" (sherpa-onnx) | "unavailable"
    llm: str  # "mock" | "openai"


@router.get("/capabilities", response_model=Capabilities)
def get_capabilities() -> Capabilities:
    from app.providers.sherpa_onnx_asr import models_available

    mode = os.environ.get("ARIAD_MODE", "demo")
    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    sherpa_models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")

    if mode == "provider":
        # Arbitrary uploads use the local sherpa-onnx ASR provider (see
        # app.dependencies.get_asr_provider); the built-in sample always
        # works via the demo provider regardless of mode.
        asr = "local" if models_available(sherpa_models_dir) else "unavailable"
    else:
        asr = "demo"

    return Capabilities(
        mode=mode,
        ffmpeg=shutil.which("ffmpeg") is not None,
        sample_audio=sample_is_available("sample_consultation"),
        asr=asr,
        llm="openai" if (mode == "provider" and has_openai_key) else "mock",
    )

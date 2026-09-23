"""Provider boundary (docs/ARCHITECTURE.md section 6).

Routes and pipeline code depend only on this Protocol so a real LLM provider
can be swapped in later without touching domain or route code.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from app.observability import StageTimer


class LLMProvider(Protocol):
    def generate_json(
        self, prompt_id: str, payload: dict[str, Any], stage_timer: Optional[StageTimer] = None
    ) -> dict[str, Any]: ...

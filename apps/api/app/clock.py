"""Injectable time source (docs/CLAUDE.md: 시간·provider·저장소 의존성은 주입한다)."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

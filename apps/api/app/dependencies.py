"""FastAPI dependency wiring: one SQLite connection per request, one shared
mock provider instance (docs/ARCHITECTURE.md: local default provider)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from app import db
from app.providers.mock import MockLLMProvider
from app.repositories.sqlite_repo import EncounterRepository

_llm_provider = MockLLMProvider()


def get_db_path() -> str:
    return os.environ.get("ARIAD_DB_PATH", "./data/ariad.db")


def get_repository() -> Iterator[EncounterRepository]:
    conn = db.connect(get_db_path())
    try:
        yield EncounterRepository(conn)
    finally:
        conn.close()


def get_llm_provider() -> MockLLMProvider:
    return _llm_provider

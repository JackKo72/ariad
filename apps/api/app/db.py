"""SQLite connection + schema (docs/ARCHITECTURE.md: Local DB: SQLite).

Only IDs, hashes, status, and timestamps are meant to live in ancillary
tables like audit_events -- never transcript/structure/explanation bodies
(docs/DEBUGGING.md structured log fields).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS encounters (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    consent_confirmed INTEGER NOT NULL,
    error_code TEXT,
    public_token TEXT UNIQUE,
    current_draft_version_id TEXT,
    approved_version_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS encounter_versions (
    id TEXT PRIMARY KEY,
    encounter_id TEXT NOT NULL REFERENCES encounters(id),
    version_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    transcript_text TEXT NOT NULL,
    structure_json TEXT NOT NULL,
    explanation_json TEXT NOT NULL,
    prompt_version_structure TEXT,
    prompt_version_explanation TEXT,
    created_at TEXT NOT NULL,
    approved_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    encounter_id TEXT NOT NULL REFERENCES encounters(id),
    event_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- tasks/02_AUDIO_PIPELINE.md Phase A. storage_path is a server-generated
-- path, never derived from the user's filename (path traversal guard);
-- sha256_hash is kept for future duplicate detection but is never returned
-- by the API (docs/DEBUGGING.md: never expose hashes tying back to content).
CREATE TABLE IF NOT EXISTS audio_assets (
    id TEXT PRIMARY KEY,
    encounter_id TEXT NOT NULL REFERENCES encounters(id),
    kind TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    original_filename TEXT,
    mime_type TEXT,
    size_bytes INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    sha256_hash TEXT NOT NULL,
    preprocessing_mode TEXT,
    source_asset_id TEXT,
    sample_id TEXT,
    created_at TEXT NOT NULL
);

-- tasks/02_AUDIO_PIPELINE.md Phase C. Tracks ASR/diarization/role-assignment
-- state for an audio-derived encounter, separate from EncounterStatus.
-- segments_json/roles_json hold DiarizedSegment[] / {speaker: role} --
-- structured facts derived from the transcript, not the transcript prose
-- itself, so this stays consistent with docs/DEBUGGING.md's "no
-- transcript/explanation bodies in ancillary tables" spirit as far as a
-- local-only, gitignored dev DB allows.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    encounter_id TEXT NOT NULL REFERENCES encounters(id),
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    audio_asset_id TEXT,
    sample_id TEXT,
    segments_json TEXT NOT NULL,
    roles_json TEXT NOT NULL,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1. One row per StageRecord
-- (app/observability.py). Only the fields docs/DEBUGGING.md's allowlist
-- covers -- never audio, transcript, or explanation content.
CREATE TABLE IF NOT EXISTS stage_runs (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    encounter_id TEXT,
    pipeline_run_id TEXT,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    audio_duration_seconds REAL,
    file_size_bytes INTEGER,
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    schema_version TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_hit INTEGER,
    error_code TEXT,
    created_at TEXT NOT NULL
);
"""

# Columns added after the first release of a table above. SQLite has no
# "ADD COLUMN IF NOT EXISTS", so existing local dev DBs (never migrated,
# always gitignored) are patched in place instead of forcing a manual
# delete-and-recreate every time the schema grows.
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("audio_assets", "preprocessing_mode", "ALTER TABLE audio_assets ADD COLUMN preprocessing_mode TEXT"),
    ("audio_assets", "source_asset_id", "ALTER TABLE audio_assets ADD COLUMN source_asset_id TEXT"),
    ("audio_assets", "sample_id", "ALTER TABLE audio_assets ADD COLUMN sample_id TEXT"),
]


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    for table, column, ddl in _COLUMN_MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(ddl)


def connect(db_path: str) -> sqlite3.Connection:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _apply_column_migrations(conn)
    return conn


@contextmanager
def session(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()

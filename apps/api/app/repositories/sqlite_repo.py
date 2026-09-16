"""Encounter/version/audit persistence (docs/ARCHITECTURE.md Repository row).

Owns SQLite access and immutability bookkeeping only -- no clinical
transformation happens here (that's app/pipeline). Time and ID generation
are injected so tests can pass fakes if needed.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable, Optional

from app.clock import utc_now_iso
from app.domain.errors import ApprovalStaleVersion, NotFoundError, PublishNotApproved
from app.domain.models import (
    AudioAsset,
    ClinicalStructure,
    Encounter,
    EncounterStatus,
    EncounterVersion,
    ExplanationDraft,
    VersionStatus,
)
from app.domain.state_machine import ensure_status, ensure_transition
from app.ids import new_id, new_public_token


def _row_to_encounter(row: sqlite3.Row) -> Encounter:
    return Encounter(
        id=row["id"],
        status=EncounterStatus(row["status"]),
        consent_confirmed=bool(row["consent_confirmed"]),
        error_code=row["error_code"],
        public_token=row["public_token"],
        current_draft_version_id=row["current_draft_version_id"],
        approved_version_id=row["approved_version_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_version(row: sqlite3.Row) -> EncounterVersion:
    return EncounterVersion(
        id=row["id"],
        encounter_id=row["encounter_id"],
        version_number=row["version_number"],
        status=VersionStatus(row["status"]),
        transcript_text=row["transcript_text"],
        structure=ClinicalStructure.model_validate(json.loads(row["structure_json"])),
        explanation=ExplanationDraft.model_validate(json.loads(row["explanation_json"])),
        prompt_version_structure=row["prompt_version_structure"],
        prompt_version_explanation=row["prompt_version_explanation"],
        created_at=row["created_at"],
        approved_at=row["approved_at"],
    )


def _row_to_audio_asset(row: sqlite3.Row) -> AudioAsset:
    return AudioAsset(
        id=row["id"],
        encounter_id=row["encounter_id"],
        kind=row["kind"],
        original_filename=row["original_filename"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        duration_seconds=row["duration_seconds"],
        created_at=row["created_at"],
    )


class EncounterRepository:
    def __init__(self, conn: sqlite3.Connection, *, clock: Callable[[], str] = utc_now_iso):
        self._conn = conn
        self._now = clock

    # -- reads ---------------------------------------------------------

    def get_encounter(self, encounter_id: str) -> Encounter:
        row = self._conn.execute(
            "SELECT * FROM encounters WHERE id = ?", (encounter_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Encounter")
        return _row_to_encounter(row)

    def get_encounter_by_public_token(self, token: str) -> Optional[Encounter]:
        row = self._conn.execute(
            "SELECT * FROM encounters WHERE public_token = ?", (token,)
        ).fetchone()
        return _row_to_encounter(row) if row else None

    def get_version(self, version_id: str) -> EncounterVersion:
        row = self._conn.execute(
            "SELECT * FROM encounter_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("EncounterVersion")
        return _row_to_version(row)

    def list_encounters(self) -> list[Encounter]:
        rows = self._conn.execute("SELECT * FROM encounters ORDER BY created_at DESC").fetchall()
        return [_row_to_encounter(row) for row in rows]

    # -- writes ----------------------------------------------------------

    def create_encounter(self, *, consent_confirmed: bool) -> Encounter:
        encounter_id = new_id()
        now = self._now()
        self._conn.execute(
            """INSERT INTO encounters
               (id, status, consent_confirmed, error_code, public_token,
                current_draft_version_id, approved_version_id, created_at, updated_at)
               VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)""",
            (encounter_id, EncounterStatus.DRAFT.value, int(consent_confirmed), now, now),
        )
        self._add_audit_event(encounter_id, "ENCOUNTER_CREATED", {})
        self._conn.commit()
        return self.get_encounter(encounter_id)

    def submit_input(self, encounter_id: str, transcript_text: str) -> Encounter:
        encounter = self.get_encounter(encounter_id)
        ensure_transition(encounter.status, EncounterStatus.SUBMITTED, "input")
        version_id = new_id()
        now = self._now()
        empty_structure = ClinicalStructure().model_dump_json()
        empty_explanation = ExplanationDraft().model_dump_json()
        self._conn.execute(
            """INSERT INTO encounter_versions
               (id, encounter_id, version_number, status, transcript_text,
                structure_json, explanation_json, prompt_version_structure,
                prompt_version_explanation, created_at, approved_at)
               VALUES (?, ?, 1, 'draft', ?, ?, ?, NULL, NULL, ?, NULL)""",
            (version_id, encounter_id, transcript_text, empty_structure, empty_explanation, now),
        )
        self._conn.execute(
            """UPDATE encounters
               SET status = ?, current_draft_version_id = ?, updated_at = ?
               WHERE id = ?""",
            (EncounterStatus.SUBMITTED.value, version_id, now, encounter_id),
        )
        self._add_audit_event(
            encounter_id, "INPUT_SUBMITTED", {"version_id": version_id, "transcript_len": len(transcript_text)}
        )
        self._conn.commit()
        return self.get_encounter(encounter_id)

    def start_processing(self, encounter_id: str) -> Encounter:
        encounter = self.get_encounter(encounter_id)
        ensure_status(
            encounter.status,
            {EncounterStatus.SUBMITTED, EncounterStatus.PROCESSING_FAILED},
            "process",
        )
        now = self._now()
        self._conn.execute(
            "UPDATE encounters SET status = ?, error_code = NULL, updated_at = ? WHERE id = ?",
            (EncounterStatus.PROCESSING.value, now, encounter_id),
        )
        self._add_audit_event(encounter_id, "PIPELINE_STARTED", {})
        self._conn.commit()
        return self.get_encounter(encounter_id)

    def complete_processing(
        self,
        encounter_id: str,
        *,
        structure: ClinicalStructure,
        explanation: ExplanationDraft,
        prompt_version_structure: str,
        prompt_version_explanation: str,
    ) -> Encounter:
        encounter = self.get_encounter(encounter_id)
        ensure_status(encounter.status, {EncounterStatus.PROCESSING}, "complete_processing")
        now = self._now()
        self._conn.execute(
            """UPDATE encounter_versions
               SET structure_json = ?, explanation_json = ?,
                   prompt_version_structure = ?, prompt_version_explanation = ?
               WHERE id = ?""",
            (
                structure.model_dump_json(),
                explanation.model_dump_json(),
                prompt_version_structure,
                prompt_version_explanation,
                encounter.current_draft_version_id,
            ),
        )
        self._conn.execute(
            "UPDATE encounters SET status = ?, updated_at = ? WHERE id = ?",
            (EncounterStatus.REVIEW_REQUIRED.value, now, encounter_id),
        )
        self._add_audit_event(
            encounter_id,
            "PIPELINE_SUCCEEDED",
            {"version_id": encounter.current_draft_version_id},
        )
        self._conn.commit()
        return self.get_encounter(encounter_id)

    def fail_processing(self, encounter_id: str, *, error_code: str) -> Encounter:
        encounter = self.get_encounter(encounter_id)
        ensure_status(encounter.status, {EncounterStatus.PROCESSING}, "fail_processing")
        now = self._now()
        self._conn.execute(
            "UPDATE encounters SET status = ?, error_code = ?, updated_at = ? WHERE id = ?",
            (EncounterStatus.PROCESSING_FAILED.value, error_code, now, encounter_id),
        )
        self._add_audit_event(encounter_id, "PIPELINE_FAILED", {"error_code": error_code})
        self._conn.commit()
        return self.get_encounter(encounter_id)

    def update_draft(
        self,
        encounter_id: str,
        *,
        structure: ClinicalStructure,
        explanation: ExplanationDraft,
        expected_version_number: int,
    ) -> Encounter:
        encounter = self.get_encounter(encounter_id)
        ensure_status(
            encounter.status,
            {EncounterStatus.REVIEW_REQUIRED, EncounterStatus.APPROVED},
            "update_draft",
        )

        if encounter.status == EncounterStatus.APPROVED:
            # Editing an approved encounter clones a new draft version; the
            # approved row itself is never mutated (docs/PRODUCT.md section 6).
            approved = self.get_version(encounter.approved_version_id)  # type: ignore[arg-type]
            if approved.version_number != expected_version_number:
                raise ApprovalStaleVersion()
            new_version_id = new_id()
            now = self._now()
            self._conn.execute(
                """INSERT INTO encounter_versions
                   (id, encounter_id, version_number, status, transcript_text,
                    structure_json, explanation_json, prompt_version_structure,
                    prompt_version_explanation, created_at, approved_at)
                   VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    new_version_id,
                    encounter_id,
                    approved.version_number + 1,
                    approved.transcript_text,
                    structure.model_dump_json(),
                    explanation.model_dump_json(),
                    approved.prompt_version_structure,
                    approved.prompt_version_explanation,
                    now,
                ),
            )
            self._conn.execute(
                """UPDATE encounters
                   SET status = ?, current_draft_version_id = ?, updated_at = ?
                   WHERE id = ?""",
                (EncounterStatus.REVIEW_REQUIRED.value, new_version_id, now, encounter_id),
            )
            self._add_audit_event(
                encounter_id,
                "DRAFT_UPDATED",
                {"version_id": new_version_id, "cloned_from_approved": True},
            )
            self._conn.commit()
            return self.get_encounter(encounter_id)

        draft = self.get_version(encounter.current_draft_version_id)  # type: ignore[arg-type]
        if draft.version_number != expected_version_number:
            raise ApprovalStaleVersion()
        now = self._now()
        self._conn.execute(
            "UPDATE encounter_versions SET structure_json = ?, explanation_json = ? WHERE id = ?",
            (structure.model_dump_json(), explanation.model_dump_json(), draft.id),
        )
        self._conn.execute(
            "UPDATE encounters SET updated_at = ? WHERE id = ?", (now, encounter_id)
        )
        self._add_audit_event(encounter_id, "DRAFT_UPDATED", {"version_id": draft.id})
        self._conn.commit()
        return self.get_encounter(encounter_id)

    def approve(self, encounter_id: str, *, expected_version_number: int) -> Encounter:
        encounter = self.get_encounter(encounter_id)
        ensure_transition(encounter.status, EncounterStatus.APPROVED, "approve")
        draft = self.get_version(encounter.current_draft_version_id)  # type: ignore[arg-type]
        if draft.version_number != expected_version_number:
            raise ApprovalStaleVersion()
        now = self._now()
        self._conn.execute(
            "UPDATE encounter_versions SET status = 'approved', approved_at = ? WHERE id = ?",
            (now, draft.id),
        )
        self._conn.execute(
            "UPDATE encounters SET status = ?, approved_version_id = ?, updated_at = ? WHERE id = ?",
            (EncounterStatus.APPROVED.value, draft.id, now, encounter_id),
        )
        self._add_audit_event(encounter_id, "APPROVED", {"version_id": draft.id})
        self._conn.commit()
        return self.get_encounter(encounter_id)

    def publish(self, encounter_id: str) -> Encounter:
        encounter = self.get_encounter(encounter_id)
        if encounter.status != EncounterStatus.APPROVED:
            raise PublishNotApproved()
        ensure_transition(encounter.status, EncounterStatus.PUBLISHED, "publish")
        token = new_public_token()
        now = self._now()
        self._conn.execute(
            "UPDATE encounters SET status = ?, public_token = ?, updated_at = ? WHERE id = ?",
            (EncounterStatus.PUBLISHED.value, token, now, encounter_id),
        )
        self._add_audit_event(encounter_id, "PUBLISHED", {"public_token_set": True})
        self._conn.commit()
        return self.get_encounter(encounter_id)

    def revoke(self, encounter_id: str) -> Encounter:
        encounter = self.get_encounter(encounter_id)
        ensure_transition(encounter.status, EncounterStatus.REVOKED, "revoke")
        now = self._now()
        self._conn.execute(
            "UPDATE encounters SET status = ?, updated_at = ? WHERE id = ?",
            (EncounterStatus.REVOKED.value, now, encounter_id),
        )
        self._add_audit_event(encounter_id, "REVOKED", {})
        self._conn.commit()
        return self.get_encounter(encounter_id)

    # -- audio assets (tasks/02_AUDIO_PIPELINE.md Phase A) ------------------

    def create_audio_asset(
        self,
        encounter_id: str,
        *,
        kind: str,
        storage_path: str,
        original_filename: Optional[str],
        mime_type: Optional[str],
        size_bytes: int,
        duration_seconds: float,
        sha256_hash: str,
    ) -> AudioAsset:
        # Uploading is only meaningful before a transcript exists; reuses the
        # same DRAFT guard input/other Task 01 entry points use instead of
        # inventing a parallel status check.
        encounter = self.get_encounter(encounter_id)
        ensure_status(encounter.status, {EncounterStatus.DRAFT}, "upload_audio")

        asset_id = new_id()
        now = self._now()
        self._conn.execute(
            """INSERT INTO audio_assets
               (id, encounter_id, kind, storage_path, original_filename, mime_type,
                size_bytes, duration_seconds, sha256_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                asset_id,
                encounter_id,
                kind,
                storage_path,
                original_filename,
                mime_type,
                size_bytes,
                duration_seconds,
                sha256_hash,
                now,
            ),
        )
        self._add_audit_event(
            encounter_id, "AUDIO_UPLOADED", {"asset_id": asset_id, "size_bytes": size_bytes}
        )
        self._conn.commit()
        return self.get_audio_asset(asset_id)

    def get_audio_asset(self, asset_id: str) -> AudioAsset:
        row = self._conn.execute(
            "SELECT * FROM audio_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("AudioAsset")
        return _row_to_audio_asset(row)

    def get_audio_asset_storage_path(self, asset_id: str) -> str:
        row = self._conn.execute(
            "SELECT storage_path FROM audio_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("AudioAsset")
        return row["storage_path"]

    def list_audio_assets(self, encounter_id: str) -> list[AudioAsset]:
        rows = self._conn.execute(
            "SELECT * FROM audio_assets WHERE encounter_id = ? ORDER BY created_at", (encounter_id,)
        ).fetchall()
        return [_row_to_audio_asset(row) for row in rows]

    # -- audit -------------------------------------------------------------

    def _add_audit_event(self, encounter_id: str, event_type: str, metadata: dict) -> None:
        self._conn.execute(
            "INSERT INTO audit_events (id, encounter_id, event_type, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_id(), encounter_id, event_type, json.dumps(metadata), self._now()),
        )

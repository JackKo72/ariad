"""Patient-facing public route.

Only ever returns the approved explanation of a PUBLISHED encounter -- never
the transcript, structure, or validation report (docs/ARCHITECTURE.md
section 7: "공개 token으로 원음, 전체 전사, 내부 validation report를 조회할
수 없다"). A token that does not resolve to a currently-published encounter
returns 404 with no distinguishing detail, so an unapproved/revoked
encounter cannot be told apart from a nonexistent token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.domain.models import EncounterStatus, ExplanationDraft
from app.repositories.sqlite_repo import EncounterRepository

from app.dependencies import get_repository

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/explanations/{token}", response_model=ExplanationDraft)
def get_public_explanation(
    token: str, repo: EncounterRepository = Depends(get_repository)
) -> ExplanationDraft:
    encounter = repo.get_encounter_by_public_token(token)
    if encounter is None or encounter.status != EncounterStatus.PUBLISHED:
        raise HTTPException(status_code=404, detail="Not found")
    approved = repo.get_version(encounter.approved_version_id)  # type: ignore[arg-type]
    return approved.explanation

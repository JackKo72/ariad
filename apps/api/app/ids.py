"""ID and public-token generation."""

from __future__ import annotations

import secrets
import uuid


def new_id() -> str:
    return uuid.uuid4().hex


def new_public_token() -> str:
    # URL-safe, unguessable. Not a session credential -- see docs/ARCHITECTURE.md
    # section 7: token only ever resolves a PUBLISHED encounter's approved version.
    return secrets.token_urlsafe(24)

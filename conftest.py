"""Repo-root pytest bootstrap: makes apps/api importable as `app.*` for both
apps/api/tests (unit/contract) and tests/integration (API+DB)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "apps" / "api"))

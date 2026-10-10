"""Load catalog/actions.yaml into the validated Catalog model."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.domain.stage2 import Catalog

CATALOG_PATH = Path(__file__).resolve().parents[4] / "catalog" / "actions.yaml"


def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    return Catalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

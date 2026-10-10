"""Export stage 2 pydantic models to JSON Schema (docs/ARIAD_stage2_design.md Step 2).

Writes one file per model into packages/contracts/schema/stage2/.
apps/api/tests/test_stage2_schemas.py fails if the checked-in files drift
from the models, so rerun this after any change to app/domain/stage2.py:

    python3 scripts/export_stage2_schemas.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.domain import stage2  # noqa: E402

OUT_DIR = REPO_ROOT / "packages" / "contracts" / "schema" / "stage2"
EXPORTED_MODELS = (
    stage2.ActionDirective,
    stage2.CatalogAction,
    stage2.ActionItem,
    stage2.ActionPlan,
    stage2.CheckIn,
    stage2.AdherenceJudgment,
    stage2.BarrierReport,
)


def render_schemas() -> dict[str, str]:
    """file name -> JSON text, for every exported model."""
    return {
        f"{model.__name__}.schema.json": json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
        for model in EXPORTED_MODELS
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in render_schemas().items():
        (OUT_DIR / name).write_text(text, encoding="utf-8")
        print(f"wrote {(OUT_DIR / name).relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

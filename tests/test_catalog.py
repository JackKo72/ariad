"""Schema checks for catalog/actions.yaml (docs/ARIAD_stage2_design.md Step 1).

Checks required fields, duplicate codes, and enum values, and reports every
TODO_CLINICIAN placeholder so a clinician knows what is still unfilled.
Print the TODO report with: python tests/test_catalog.py
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog" / "actions.yaml"
TODO = "TODO_CLINICIAN"

EXPECTED_CODES = {"D1", "D2", "D3", "D4", "D5", "P1", "P2", "P3", "W1", "A1", "S1", "M1", "H1", "H2"}
REQUIRED_FIELDS = (
    "catalog_code",
    "name_ko",
    "guideline_refs",
    "atomic_behaviors",
    "metric_type",
    "default_target",
    "check_method",
    "contraindication_rules",
    "adjustable_params",
)
METRIC_TYPES = {"frequency", "amount", "binary", "measurement"}
COMPARATORS = {">=", "<="}
TARGET_KEYS = ("value", "unit", "comparator")


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def find_todos(node: Any, path: str = "") -> list[str]:
    """Return the dotted path of every TODO_CLINICIAN value under node."""
    if node == TODO:
        return [path]
    if isinstance(node, dict):
        return [p for k, v in node.items() for p in find_todos(v, f"{path}.{k}" if path else str(k))]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in find_todos(v, f"{path}[{i}]")]
    return []


def todo_report(catalog: dict[str, Any]) -> dict[str, list[str]]:
    """catalog_code -> TODO paths inside that action (only codes with TODOs)."""
    report = {a["catalog_code"]: find_todos(a) for a in catalog["actions"]}
    return {code: paths for code, paths in report.items() if paths}


def _target_blocks(default_target: dict[str, Any]) -> list[dict[str, Any]]:
    # H1 splits its target into pre_visit/routine sub-targets.
    nested = [v for v in default_target.values() if isinstance(v, dict)]
    return nested or [default_target]


def test_catalog_has_exactly_the_14_design_codes():
    codes = [a["catalog_code"] for a in load_catalog()["actions"]]
    assert set(codes) == EXPECTED_CODES


def test_catalog_codes_are_unique():
    codes = [a["catalog_code"] for a in load_catalog()["actions"]]
    duplicates = [code for code, n in Counter(codes).items() if n > 1]
    assert duplicates == []


def test_every_action_has_all_required_fields():
    missing = [
        f"{a.get('catalog_code', '?')}.{field}"
        for a in load_catalog()["actions"]
        for field in REQUIRED_FIELDS
        if field not in a or a[field] is None
    ]
    assert missing == []


def test_guideline_refs_are_non_empty():
    empty = [a["catalog_code"] for a in load_catalog()["actions"] if not a["guideline_refs"]]
    assert empty == []


def test_metric_type_is_enum_or_todo():
    bad = [
        (a["catalog_code"], a["metric_type"])
        for a in load_catalog()["actions"]
        if a["metric_type"] not in METRIC_TYPES | {TODO}
    ]
    assert bad == []


def test_default_target_has_value_unit_comparator():
    problems = []
    for a in load_catalog()["actions"]:
        for block in _target_blocks(a["default_target"]):
            for key in TARGET_KEYS:
                if key not in block:
                    problems.append(f"{a['catalog_code']}: default_target missing {key}")
            if block.get("comparator") not in COMPARATORS | {TODO}:
                problems.append(f"{a['catalog_code']}: bad comparator {block.get('comparator')!r}")
            value = block.get("value")
            if value != TODO and not isinstance(value, (int, float)):
                problems.append(f"{a['catalog_code']}: non-numeric target value {value!r}")
    assert problems == []


def test_check_method_has_channel_and_unique_question_id():
    actions = load_catalog()["actions"]
    missing = [a["catalog_code"] for a in actions if "channel" not in a["check_method"]]
    missing += [a["catalog_code"] for a in actions if "question_id" not in a["check_method"]]
    assert missing == []
    # D4 and D5 deliberately share Q-D45-01 (Part 2-2 "D4–D5 주 1회 3문항").
    owners: dict[str, set[str]] = {}
    for a in actions:
        owners.setdefault(a["check_method"]["question_id"], set()).add(a["catalog_code"])
    shared = {qid: codes for qid, codes in owners.items() if len(codes) > 1}
    assert shared == {"Q-D45-01": {"D4", "D5"}}


def test_contraindication_rules_have_id_and_rule_text():
    bad = [
        a["catalog_code"]
        for a in load_catalog()["actions"]
        for r in a["contraindication_rules"]
        if not r.get("id") or not r.get("rule")
    ]
    assert bad == []


def test_adjustable_params_point_at_existing_fields():
    bad = []
    for a in load_catalog()["actions"]:
        for param in a["adjustable_params"]:
            node: Any = a
            for part in param.split("."):
                if not isinstance(node, dict) or part not in node:
                    bad.append(f"{a['catalog_code']}: {param}")
                    break
                node = node[part]
    assert bad == []


def test_todo_report_lists_unfilled_clinician_values(capsys):
    report = todo_report(load_catalog())
    total = sum(len(paths) for paths in report.values())
    with capsys.disabled():
        print(f"\n[catalog] TODO_CLINICIAN: {total} across {len(report)} actions")
        for code, paths in report.items():
            print(f"  {code}: {', '.join(paths)}")
    # Report-only: unfilled values are expected until a clinician reviews.
    # Guard only that every TODO is visible through the report.
    assert total == len(find_todos(load_catalog()["actions"]))


if __name__ == "__main__":
    for code, paths in todo_report(load_catalog()).items():
        print(f"{code}: {', '.join(paths)}")

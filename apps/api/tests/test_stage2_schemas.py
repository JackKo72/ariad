"""Stage 2 schema tests (docs/ARIAD_stage2_design.md Step 2).

Round-trip (serialize -> deserialize) for every entity, the cross-field
invariants, catalog/actions.yaml loading, OpenAI strict-mode compatibility
of the LLM-facing ActionDirective, and drift of the exported JSON Schemas.
All data is synthetic.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from app.domain.models import SourceSpan
from app.domain.stage2 import (
    ActionDirective,
    ActionItem,
    ActionPlan,
    ActionStatus,
    AdherenceJudgment,
    AdherenceLabel,
    Agreement,
    BarrierCode,
    BarrierMention,
    BarrierReport,
    Catalog,
    CatalogAction,
    CheckIn,
    PatientResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _span(segment_id: str, role: str, quote: str, speaker: str) -> SourceSpan:
    return SourceSpan(segment_id=segment_id, quote=quote, speaker=speaker, role=role)


def _directive() -> ActionDirective:
    return ActionDirective(
        directive_id="AD-1",
        raw_text="국물은 이제 드시지 마시고요",
        source_spans=[_span("seg_003", "doctor", "국물은 이제 드시지 마시고요", "A")],
        domain_hint="diet_sodium",
        target_hint="국물 섭취 0",
        patient_response=PatientResponse(
            text="그게 제일 어렵네요",
            agreement=Agreement.HESITANT,
            source_spans=[_span("seg_004", "patient", "그게 제일 어렵네요", "B")],
        ),
        barrier_mentions=[
            BarrierMention(
                text="혼자 살아서 라면을 자주 먹어요",
                source_spans=[_span("seg_005", "patient", "혼자 살아서 라면을 자주 먹어요", "B")],
            )
        ],
    )


def _item(**overrides) -> ActionItem:
    data = dict(
        action_id="A-001",
        plan_id="P-enc1-v1",
        catalog_code="D2",
        target={"value": 7, "unit": "days_per_week", "comparator": ">="},
        source_directive_id="AD-1",
    )
    data.update(overrides)
    return ActionItem(**data)


def _approved_item(**overrides) -> ActionItem:
    return _item(status="approved", approved_by="clinician-1", **overrides)


def _round_trip(obj: BaseModel) -> None:
    restored = type(obj).model_validate_json(obj.model_dump_json())
    assert restored == obj


# ---------------------------------------------------------------- round trips


@pytest.mark.parametrize(
    "obj",
    [
        _directive(),
        _item(),
        ActionPlan(plan_id="P-enc1-v1", encounter_id="enc1", version=1, items=[_item()], created_at="2026-10-09T10:00:00Z"),
        CheckIn(checkin_id="C-1", action_id="A-001", date="2026-10-12", value=1, source="self_report"),
        AdherenceJudgment(
            action_id="A-001", plan_id="P-enc1-v1", week="2026-W42", rate=0.43, response_rate=1.0,
            label="non_adherent", rule_version="r1",
        ),
        BarrierReport(action_id="A-001", week="2026-W42", code="O-SOC", free_text="가족이 짜게 해요", classifier_confidence=0.82),
    ],
    ids=lambda o: type(o).__name__,
)
def test_round_trip(obj):
    _round_trip(obj)


def test_directive_keeps_segment_id_speaker_and_role():
    """docs/stage1_output.md section 7: the seg_xxx ID, the A/B speaker
    label and the doctor/patient role all survive serialization."""
    dumped = _directive().model_dump()
    span = dumped["source_spans"][0]
    assert (span["segment_id"], span["speaker"], span["role"]) == ("seg_003", "A", "doctor")
    assert dumped["patient_response"]["source_spans"][0]["role"] == "patient"
    assert dumped["needs_review"] is True  # default until grounding check passes


def test_directive_minimal_defaults():
    d = ActionDirective(directive_id="AD-2", raw_text="걸으세요")
    assert d.patient_response is None and d.barrier_mentions == [] and d.needs_review is True


# ---------------------------------------------------------------- enums


def test_enums_match_design_values():
    assert {a.value for a in Agreement} == {"agreed", "hesitant", "refused", "unclear"}
    assert {s.value for s in ActionStatus} == {"draft", "approved", "active", "paused", "retired"}
    assert {c.value for c in BarrierCode} == {
        "C-PHY", "C-PSY", "O-PHY", "O-SOC", "M-REF", "M-AUT", "M-EMO", "MED", "PLAN", "MEAS",
    }


def test_unknown_agreement_rejected():
    with pytest.raises(ValidationError):
        PatientResponse(text="...", agreement="maybe")


# ---------------------------------------------------------------- ActionItem invariants


def test_draft_item_may_lack_target_and_approver():
    item = _item(target=None)
    assert item.status == ActionStatus.DRAFT and item.target is None


@pytest.mark.parametrize("status", ["approved", "active", "paused", "retired"])
def test_non_draft_item_requires_approver(status):
    with pytest.raises(ValidationError, match="approved_by"):
        _item(status=status)


def test_approved_item_requires_target():
    with pytest.raises(ValidationError, match="target"):
        _approved_item(target=None)


def test_approved_item_cannot_need_review():
    with pytest.raises(ValidationError, match="needs_review"):
        _approved_item(needs_review=True)


def test_custom_draft_requires_needs_review():
    with pytest.raises(ValidationError, match="custom"):
        _item(catalog_code="custom")
    assert _item(catalog_code="custom", needs_review=True).needs_review


def test_target_rejects_todo_placeholder():
    with pytest.raises(ValidationError):
        _item(target={"value": "TODO_CLINICIAN", "unit": "days_per_week", "comparator": ">="})


# ---------------------------------------------------------------- ActionPlan invariants


def _plan(**overrides) -> ActionPlan:
    data = dict(plan_id="P-enc1-v1", encounter_id="enc1", version=1, items=[_item()], created_at="2026-10-09T10:00:00Z")
    data.update(overrides)
    return ActionPlan(**data)


def test_plan_v2_references_previous_version():
    plan = _plan(plan_id="P-enc2-v2", version=2, previous_plan_id="P-enc1-v1", items=[_item(plan_id="P-enc2-v2")])
    assert plan.previous_plan_id == "P-enc1-v1"


def test_plan_v2_without_previous_rejected():
    with pytest.raises(ValidationError, match="previous_plan_id"):
        _plan(plan_id="P-enc2-v2", version=2, items=[])


def test_plan_v1_with_previous_rejected():
    with pytest.raises(ValidationError, match="version 1"):
        _plan(previous_plan_id="P-old")


def test_plan_self_reference_rejected():
    with pytest.raises(ValidationError, match="differ"):
        _plan(version=2, previous_plan_id="P-enc1-v1")


def test_plan_rejects_item_from_other_plan():
    with pytest.raises(ValidationError, match="another plan"):
        _plan(items=[_item(plan_id="P-other-v1")])


def test_plan_rejects_duplicate_action_ids():
    with pytest.raises(ValidationError, match="duplicate"):
        _plan(items=[_item(), _item()])


def test_approved_plan_cannot_hold_draft_items():
    with pytest.raises(ValidationError, match="draft items"):
        _plan(status="approved", approved_by="clinician-1", approved_at="2026-10-09T11:00:00Z")


def test_approved_plan_requires_approver_and_time():
    with pytest.raises(ValidationError, match="approved_by"):
        _plan(status="approved", items=[_approved_item()])
    plan = _plan(status="approved", approved_by="clinician-1", approved_at="2026-10-09T11:00:00Z", items=[_approved_item()])
    _round_trip(plan)


# ---------------------------------------------------------------- judgment / barrier


@pytest.mark.parametrize("week", ["2026-42", "2026-W00", "2026-W54", "W42"])
def test_bad_iso_week_rejected(week):
    with pytest.raises(ValidationError, match="ISO week"):
        AdherenceJudgment(action_id="A", plan_id="P", week=week, rate=0.5, response_rate=1, label="partial", rule_version="r1")


def test_indeterminate_judgment_may_omit_rate():
    j = AdherenceJudgment(action_id="A", plan_id="P", week="2026-W42", response_rate=0.2, label="indeterminate", rule_version="r1")
    assert j.rate is None and j.label == AdherenceLabel.INDETERMINATE


def test_determinate_judgment_requires_rate():
    with pytest.raises(ValidationError, match="requires rate"):
        AdherenceJudgment(action_id="A", plan_id="P", week="2026-W42", response_rate=1, label="adherent", rule_version="r1")


def test_red_flag_report_skips_code():
    report = BarrierReport(action_id="A", week="2026-W42", red_flag=True, free_text="말이 어눌해졌어요")
    assert report.code is None
    with pytest.raises(ValidationError, match="skip classification"):
        BarrierReport(action_id="A", week="2026-W42", red_flag=True, code="MED")


def test_non_red_flag_report_requires_code():
    with pytest.raises(ValidationError, match="requires a barrier code"):
        BarrierReport(action_id="A", week="2026-W42", free_text="...")


def test_classifier_confidence_bounded():
    with pytest.raises(ValidationError):
        BarrierReport(action_id="A", week="2026-W42", code="MEAS", classifier_confidence=1.2)


# ---------------------------------------------------------------- catalog


def _catalog_yaml() -> dict:
    return yaml.safe_load((REPO_ROOT / "catalog" / "actions.yaml").read_text(encoding="utf-8"))


def test_catalog_yaml_validates_against_model():
    catalog = Catalog.model_validate(_catalog_yaml())
    assert len(catalog.actions) == 14
    for action in catalog.actions:
        _round_trip(action)


def test_catalog_rejects_unknown_key():
    data = _catalog_yaml()
    data["actions"][0]["defualt_target"] = data["actions"][0].pop("default_target")
    with pytest.raises(ValidationError):
        Catalog.model_validate(data)


def test_catalog_rejects_reserved_custom_code():
    data = _catalog_yaml()
    data["actions"][0]["catalog_code"] = "custom"
    with pytest.raises(ValidationError, match="reserved"):
        Catalog.model_validate(data)


# ---------------------------------------------------------------- LLM-facing / export


def _empty_objects(node, path="$") -> list[str]:
    """Paths of object schemas that declare no properties."""
    found = []
    if isinstance(node, dict):
        if node.get("type") == "object" and not node.get("properties"):
            found.append(path)
        for key, value in node.items():
            found += _empty_objects(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += _empty_objects(value, f"{path}[{i}]")
    return found


def test_action_directive_is_openai_strict_schema_compatible():
    """Every nested object must be an explicit model for strict mode.
    type_to_response_format_param alone is not enough: this SDK version
    silently turns a free-form dict into an object with no properties
    instead of raising, so also walk the generated schema for those."""
    from openai.lib._parsing._completions import type_to_response_format_param

    class _Wrapper(BaseModel):
        action_directives: list[ActionDirective]

    schema = type_to_response_format_param(_Wrapper)["json_schema"]["schema"]
    assert _empty_objects(schema) == []


def test_exported_json_schemas_are_up_to_date():
    spec = importlib.util.spec_from_file_location("export_stage2_schemas", REPO_ROOT / "scripts" / "export_stage2_schemas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stale = [
        name
        for name, text in module.render_schemas().items()
        if not (module.OUT_DIR / name).exists() or (module.OUT_DIR / name).read_text(encoding="utf-8") != text
    ]
    assert stale == [], f"rerun: python3 scripts/export_stage2_schemas.py ({stale})"


def test_catalog_action_schema_lists_required_design_fields():
    required = set(CatalogAction.model_json_schema()["required"])
    assert {"catalog_code", "name_ko", "guideline_refs", "atomic_behaviors", "metric_type", "default_target", "check_method"} <= required

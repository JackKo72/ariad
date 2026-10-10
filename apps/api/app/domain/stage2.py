"""Stage 2 data shapes (docs/ARIAD_stage2_design.md Part 5-3, Step 2).

Two groups live here:

1. Stage-1 extension (Part 5-2): ActionDirective and its nested shapes,
   defined in app.domain.models because ClinicalStructure.action_directives
   embeds them, and re-exported here.

2. Stage-2 entities: CatalogAction (catalog/actions.yaml rows), ActionItem,
   ActionPlan, CheckIn, AdherenceJudgment, BarrierReport. Never LLM output
   directly, so they carry cross-field invariants as validators.

No clinical numbers live here -- targets and thresholds come from
catalog/ and config/ (CLAUDE.md stage 2 rules).
"""

from __future__ import annotations

import datetime as dt
import re
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Stage-1 extension shapes live in models.py (ClinicalStructure embeds them);
# re-exported here so stage 2 code imports everything from one module.
from app.domain.models import (  # noqa: F401
    ActionDirective,
    Agreement,
    BarrierMention,
    PatientResponse,
    SourceSpan,
)

TODO_CLINICIAN = "TODO_CLINICIAN"
CUSTOM_CATALOG_CODE = "custom"
_ISO_WEEK_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")


# ---------------------------------------------------------------- enums


class ActionStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


class Respondent(str, Enum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"


class BarrierCode(str, Enum):
    """Part 3-3 non-adherence reasons (COM-B + stroke-specific)."""

    C_PHY = "C-PHY"
    C_PSY = "C-PSY"
    O_PHY = "O-PHY"
    O_SOC = "O-SOC"
    M_REF = "M-REF"
    M_AUT = "M-AUT"
    M_EMO = "M-EMO"
    MED = "MED"
    PLAN = "PLAN"
    MEAS = "MEAS"


class MetricType(str, Enum):
    FREQUENCY = "frequency"
    AMOUNT = "amount"
    BINARY = "binary"
    MEASUREMENT = "measurement"


class Comparator(str, Enum):
    AT_LEAST = ">="
    AT_MOST = "<="


class AdherenceLabel(str, Enum):
    """Part 3-2 judgment labels. Thresholds live in config/judge.yaml (Step 4)."""

    ADHERENT = "adherent"
    PARTIAL = "partial"
    NON_ADHERENT = "non_adherent"
    INDETERMINATE = "indeterminate"  # 응답률 부족으로 판정 불가


class CheckInSource(str, Enum):
    SELF_REPORT = "self_report"
    DEVICE = "device"


# ---------------------------------------------------------------- normalizer LLM output


class DirectiveClassification(BaseModel):
    """prompts/classify_action_directive.md output. LLM-facing: no
    constraints the strict schema can't express; app/stage2/normalizer.py
    checks catalog_code membership and confidence range itself."""

    catalog_code: str  # a catalog code or "custom"
    confidence: float
    rationale: str


# ---------------------------------------------------------------- catalog (catalog/actions.yaml)

TodoOr = Literal["TODO_CLINICIAN"]


class Cadence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    times: int = Field(ge=1)
    per: Literal["day", "week"]


class CatalogTarget(BaseModel):
    model_config = ConfigDict(extra="allow")  # H1 pre_visit adds sessions/readings

    value: Union[float, TodoOr]
    unit: Union[str, TodoOr]
    comparator: Union[Comparator, TodoOr]


class CheckMethod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str
    question_id: str
    description: str
    cadence: Union[Cadence, str]  # str: "as_prescribed", "measurement_days", TODO
    example_question: Optional[str] = None
    answer_options: Optional[list[str]] = None
    objective_source: Optional[str] = None
    secondary_question_id: Optional[str] = None
    secondary_cadence: Optional[Cadence] = None


class CatalogRule(BaseModel):
    model_config = ConfigDict(extra="allow")  # safety rules carry their threshold

    id: str
    rule: str


class CatalogAction(BaseModel):
    """One row of catalog/actions.yaml. extra="forbid" so a typo'd key in
    the YAML fails loudly instead of being silently ignored."""

    model_config = ConfigDict(extra="forbid")

    catalog_code: str
    name_ko: str
    domain: str
    guideline_refs: list[str] = Field(min_length=1)
    guideline_values: dict[str, Any] = Field(default_factory=dict)
    atomic_behaviors: Union[list[str], TodoOr]
    metric_type: Union[MetricType, TodoOr]
    # H1 splits its target into named sub-targets (pre_visit / routine).
    default_target: Union[CatalogTarget, dict[str, CatalogTarget]]
    outcome_target: Optional[CatalogTarget] = None
    check_method: CheckMethod
    contraindication_rules: list[CatalogRule] = Field(default_factory=list)
    flags: list[CatalogRule] = Field(default_factory=list)
    safety_rules: list[CatalogRule] = Field(default_factory=list)
    adjustable_params: list[str] = Field(default_factory=list)


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str
    todo_marker: Literal["TODO_CLINICIAN"]
    actions: list[CatalogAction]

    @model_validator(mode="after")
    def _unique_codes(self) -> "Catalog":
        codes = [a.catalog_code for a in self.actions]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate catalog_code")
        if CUSTOM_CATALOG_CODE in codes:
            raise ValueError(f"'{CUSTOM_CATALOG_CODE}' is reserved for unmatched directives")
        return self


# ---------------------------------------------------------------- action plan


class ActionTarget(BaseModel):
    """A concrete, agreed target on an ActionItem -- never TODO."""

    value: float
    unit: str
    comparator: Comparator


class ActionItem(BaseModel):
    action_id: str
    plan_id: str
    catalog_code: str  # catalog code or "custom" (normalizer could not match)
    target: Optional[ActionTarget] = None  # None while the clinician has not set one
    respondent: Respondent = Respondent.PATIENT
    source_directive_id: Optional[str] = None  # None for clinician-added items
    status: ActionStatus = ActionStatus.DRAFT
    approved_by: Optional[str] = None
    needs_review: bool = False

    @model_validator(mode="after")
    def _post_draft_requires_approval(self) -> "ActionItem":
        # 승인 전 결과는 환자에게 가지 않는다: anything past draft must carry
        # who approved it and a concrete target.
        if self.status != ActionStatus.DRAFT:
            if not self.approved_by:
                raise ValueError(f"status={self.status.value} requires approved_by")
            if self.target is None:
                raise ValueError(f"status={self.status.value} requires target")
            if self.needs_review:
                raise ValueError(f"status={self.status.value} cannot have needs_review=true")
        if self.catalog_code == CUSTOM_CATALOG_CODE and self.status == ActionStatus.DRAFT and not self.needs_review:
            # Unmatched directives always need clinician review (Part 5-1 step 3).
            raise ValueError("custom draft items require needs_review=true")
        return self


class ActionPlan(BaseModel):
    """Versioned plan. A changed target at a revisit makes a new version
    pointing at the previous plan_id; past judgments keep their own
    plan_id, so trends are computed against the target of that time."""

    plan_id: str
    encounter_id: str  # stage-1 has no visit_id; encounter_id is the visit key
    version: int = Field(ge=1)
    previous_plan_id: Optional[str] = None
    status: ActionStatus = ActionStatus.DRAFT
    items: list[ActionItem] = Field(default_factory=list)
    created_at: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None

    @model_validator(mode="after")
    def _check_version_chain_and_items(self) -> "ActionPlan":
        if self.version == 1 and self.previous_plan_id is not None:
            raise ValueError("version 1 cannot reference a previous plan")
        if self.version > 1 and not self.previous_plan_id:
            raise ValueError(f"version {self.version} requires previous_plan_id")
        if self.previous_plan_id == self.plan_id:
            raise ValueError("previous_plan_id must differ from plan_id")
        foreign = [i.action_id for i in self.items if i.plan_id != self.plan_id]
        if foreign:
            raise ValueError(f"items belong to another plan: {foreign}")
        ids = [i.action_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate action_id in plan")
        if self.status != ActionStatus.DRAFT:
            if not (self.approved_by and self.approved_at):
                raise ValueError(f"plan status={self.status.value} requires approved_by and approved_at")
            if any(i.status == ActionStatus.DRAFT for i in self.items):
                raise ValueError("approved plan cannot contain draft items")
        return self


# ---------------------------------------------------------------- check-in / judgment / barrier


def _check_iso_week(value: str) -> str:
    if not _ISO_WEEK_RE.match(value):
        raise ValueError(f"week must be ISO week like 2026-W42, got {value!r}")
    return value


class CheckIn(BaseModel):
    checkin_id: str
    action_id: str
    date: dt.date
    value: float
    source: CheckInSource
    respondent: Respondent = Respondent.PATIENT


class AdherenceJudgment(BaseModel):
    action_id: str
    plan_id: str  # judged against this plan version's target
    week: str
    rate: Optional[float] = Field(default=None, ge=0)  # may exceed 1 (over-achievement)
    response_rate: float = Field(ge=0, le=1)
    label: AdherenceLabel
    rule_version: str

    @field_validator("week")
    @classmethod
    def _iso_week(cls, value: str) -> str:
        return _check_iso_week(value)

    @model_validator(mode="after")
    def _rate_required_unless_indeterminate(self) -> "AdherenceJudgment":
        if self.label != AdherenceLabel.INDETERMINATE and self.rate is None:
            raise ValueError(f"label={self.label.value} requires rate")
        return self


class BarrierReport(BaseModel):
    """free_text is patient-written content: store it, never log it."""

    action_id: str
    week: str
    code: Optional[BarrierCode] = None
    free_text: Optional[str] = None
    classifier_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    red_flag: bool = False
    follow_up_question: Optional[str] = None
    needs_review: bool = False

    @field_validator("week")
    @classmethod
    def _iso_week(cls, value: str) -> str:
        return _check_iso_week(value)

    @model_validator(mode="after")
    def _red_flag_skips_classification(self) -> "BarrierReport":
        # Part 3-3: red flag is handled before (and instead of) classification.
        if self.red_flag and self.code is not None:
            raise ValueError("red_flag reports skip classification: code must be None")
        if not self.red_flag and self.code is None:
            raise ValueError("non-red-flag report requires a barrier code")
        return self

"""Load stage 2 YAML config and question templates into validated models."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.domain.stage2 import CheckinConfig, JudgeConfig, QuestionBank

REPO_ROOT = Path(__file__).resolve().parents[4]
JUDGE_CONFIG_PATH = REPO_ROOT / "config" / "judge.yaml"
CHECKIN_CONFIG_PATH = REPO_ROOT / "config" / "checkin.yaml"
QUESTIONS_PATH = REPO_ROOT / "catalog" / "questions.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_judge_config(path: Path = JUDGE_CONFIG_PATH) -> JudgeConfig:
    return JudgeConfig.model_validate(_load_yaml(path))


def load_checkin_config(path: Path = CHECKIN_CONFIG_PATH) -> CheckinConfig:
    return CheckinConfig.model_validate(_load_yaml(path))


def load_question_bank(path: Path = QUESTIONS_PATH) -> QuestionBank:
    return QuestionBank.model_validate(_load_yaml(path))

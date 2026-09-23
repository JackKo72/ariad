"""Unit: StageTimer (tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1)."""

import pytest

from app.observability import StageTimer


def test_records_duration_and_ok_status():
    timer = StageTimer()
    with timer.stage("asr_total"):
        pass
    assert len(timer.records) == 1
    record = timer.records[0]
    assert record.stage == "asr_total"
    assert record.status == "ok"
    assert record.error_code is None
    assert record.duration_ms >= 0


def test_fixed_kwargs_and_meta_dict_both_land_on_the_record():
    timer = StageTimer()
    with timer.stage("structure_llm", provider="openai", model="gpt-4o-mini") as meta:
        meta["input_tokens"] = 123
        meta["output_tokens"] = 45
    record = timer.records[0]
    assert record.provider == "openai"
    assert record.model == "gpt-4o-mini"
    assert record.input_tokens == 123
    assert record.output_tokens == 45


def test_exception_is_recorded_as_error_and_reraised():
    class _Coded(Exception):
        code = "LLM_PROVIDER_FAILED"

    timer = StageTimer()
    with pytest.raises(_Coded):
        with timer.stage("structure_llm"):
            raise _Coded("boom")

    record = timer.records[0]
    assert record.status == "error"
    assert record.error_code == "LLM_PROVIDER_FAILED"


def test_exception_without_code_attribute_uses_class_name():
    timer = StageTimer()
    with pytest.raises(ValueError):
        with timer.stage("database_write"):
            raise ValueError("bad")

    record = timer.records[0]
    assert record.status == "error"
    assert record.error_code == "ValueError"


def test_multiple_stages_append_in_order():
    timer = StageTimer()
    with timer.stage("a"):
        pass
    with timer.stage("b"):
        pass
    assert [r.stage for r in timer.records] == ["a", "b"]

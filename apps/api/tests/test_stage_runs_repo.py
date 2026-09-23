"""Unit: EncounterRepository.record_stage_runs/list_stage_runs
(tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1)."""

from app import db
from app.observability import StageRecord
from app.repositories.sqlite_repo import EncounterRepository


def _repo() -> EncounterRepository:
    conn = db.connect(":memory:")
    return EncounterRepository(conn)


def test_record_stage_runs_persists_all_fields():
    repo = _repo()
    encounter = repo.create_encounter(consent_confirmed=True)
    records = [
        StageRecord(
            stage="asr_model_load",
            duration_ms=1234.5,
            provider="sherpa_onnx",
            model="whisper-large-v3",
        ),
        StageRecord(
            stage="structure_llm",
            duration_ms=800.0,
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            cache_hit=False,
        ),
    ]
    repo.record_stage_runs(
        request_id="req-1", encounter_id=encounter.id, pipeline_run_id=None, records=records
    )

    rows = repo.list_stage_runs(encounter_id=encounter.id)
    assert len(rows) == 2
    assert rows[0]["stage"] == "asr_model_load"
    assert rows[0]["duration_ms"] == 1234.5
    assert rows[0]["provider"] == "sherpa_onnx"
    assert rows[1]["stage"] == "structure_llm"
    assert rows[1]["input_tokens"] == 100
    assert rows[1]["cache_hit"] == 0


def test_record_stage_runs_is_a_noop_for_empty_list():
    repo = _repo()
    repo.record_stage_runs(request_id="req-1", encounter_id=None, pipeline_run_id=None, records=[])
    assert repo.list_stage_runs() == []


def test_list_stage_runs_without_encounter_id_returns_all():
    repo = _repo()
    e1 = repo.create_encounter(consent_confirmed=True)
    e2 = repo.create_encounter(consent_confirmed=True)
    repo.record_stage_runs(
        request_id="req-1", encounter_id=e1.id, pipeline_run_id=None,
        records=[StageRecord(stage="total", duration_ms=1.0)],
    )
    repo.record_stage_runs(
        request_id="req-2", encounter_id=e2.id, pipeline_run_id=None,
        records=[StageRecord(stage="total", duration_ms=2.0)],
    )
    assert len(repo.list_stage_runs()) == 2
    assert len(repo.list_stage_runs(encounter_id=e1.id)) == 1


def test_error_status_and_error_code_are_persisted():
    repo = _repo()
    encounter = repo.create_encounter(consent_confirmed=True)
    repo.record_stage_runs(
        request_id="req-1",
        encounter_id=encounter.id,
        pipeline_run_id=None,
        records=[StageRecord(stage="structure_llm", duration_ms=5.0, status="error", error_code="LLM_PROVIDER_FAILED")],
    )
    row = repo.list_stage_runs(encounter_id=encounter.id)[0]
    assert row["status"] == "error"
    assert row["error_code"] == "LLM_PROVIDER_FAILED"

    # No audio/transcript/explanation content anywhere in the row's values.
    for value in row.values():
        assert value != "의사: 혈압약 5mg 하루 한 번 복용하세요."

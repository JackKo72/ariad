"""Unit: pure segment-merging/filtering logic ported from asr_pipeline.py
(tasks/02_AUDIO_PIPELINE.md section 8). No sherpa_onnx import needed --
these functions never touch a model."""

import pytest

from app.providers.sherpa_onnx_asr import (
    DiarizationTurn,
    is_garbage_text,
    merge_adjacent_same_speaker,
    merge_diarization_turns,
    models_available,
)


class TestMergeDiarizationTurns:
    def test_merges_same_speaker_turns_within_gap(self):
        turns = [DiarizationTurn(0.0, 2.0, 0), DiarizationTurn(2.3, 4.0, 0)]
        merged = merge_diarization_turns(turns, merge_gap_seconds=0.8)
        assert merged == [DiarizationTurn(0.0, 4.0, 0)]

    def test_does_not_merge_across_a_large_gap(self):
        turns = [DiarizationTurn(0.0, 2.0, 0), DiarizationTurn(5.0, 6.0, 0)]
        merged = merge_diarization_turns(turns, merge_gap_seconds=0.8)
        assert merged == turns

    def test_does_not_merge_different_speakers(self):
        turns = [DiarizationTurn(0.0, 2.0, 0), DiarizationTurn(2.1, 4.0, 1)]
        merged = merge_diarization_turns(turns, merge_gap_seconds=0.8)
        assert merged == turns

    def test_splits_turns_longer_than_the_max(self):
        turns = [DiarizationTurn(0.0, 60.0, 0)]
        split = merge_diarization_turns(turns, max_segment_seconds=28.0, merge_gap_seconds=0.8)
        assert len(split) == 3  # ceil(60/28) = 3
        assert split[0].start == 0.0
        assert split[-1].end == 60.0
        for a, b in zip(split, split[1:]):
            assert a.end == b.start
            assert a.speaker_index == b.speaker_index == 0


class TestIsGarbageText:
    def test_real_korean_speech_is_not_garbage(self):
        assert not is_garbage_text("오늘 혈압이 조금 높게 나왔습니다.", speech_seconds=2.0)

    def test_near_silence_is_garbage(self):
        assert is_garbage_text("네", speech_seconds=0.1)

    def test_punctuation_only_is_garbage(self):
        assert is_garbage_text("...", speech_seconds=1.0)

    def test_non_korean_non_latin_script_is_garbage(self):
        # The pipeline is Korean+English code-switching (see module
        # docstring), so English is legitimate; a stray CJK/Cyrillic/etc.
        # fragment is what actually signals hallucination here.
        assert is_garbage_text("这是中文文本", speech_seconds=1.0)

    def test_english_is_not_garbage_by_itself(self):
        assert not is_garbage_text("Thank you for watching", speech_seconds=1.0)

    def test_known_hallucination_phrase_is_garbage(self):
        assert is_garbage_text("이곳은 한국 공공기관입니다", speech_seconds=1.0)


class TestMergeAdjacentSameSpeaker:
    def test_merges_close_same_speaker_rows(self):
        rows = [
            {"start": 0.0, "end": 2.0, "speaker_index": 0, "text": "안녕하세요"},
            {"start": 2.5, "end": 4.0, "speaker_index": 0, "text": "오늘 혈압이 높아요"},
        ]
        merged = merge_adjacent_same_speaker(rows, gap_seconds=8.0)
        assert len(merged) == 1
        assert merged[0]["text"] == "안녕하세요 오늘 혈압이 높아요"
        assert merged[0]["end"] == 4.0

    def test_does_not_merge_different_speakers_regardless_of_gap(self):
        rows = [
            {"start": 0.0, "end": 2.0, "speaker_index": 0, "text": "안녕하세요"},
            {"start": 2.1, "end": 4.0, "speaker_index": 1, "text": "네 안녕하세요"},
        ]
        merged = merge_adjacent_same_speaker(rows, gap_seconds=8.0)
        assert len(merged) == 2

    def test_does_not_merge_across_a_long_pause(self):
        rows = [
            {"start": 0.0, "end": 2.0, "speaker_index": 0, "text": "첫 문장"},
            {"start": 20.0, "end": 22.0, "speaker_index": 0, "text": "둘째 문장"},
        ]
        merged = merge_adjacent_same_speaker(rows, gap_seconds=8.0)
        assert len(merged) == 2


def test_models_available_is_false_without_model_files(tmp_path):
    assert not models_available(str(tmp_path))


def test_models_available_is_true_when_all_files_present(tmp_path):
    (tmp_path / "sherpa-onnx-whisper-large-v3").mkdir()
    (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-encoder.int8.onnx").touch()
    (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-decoder.int8.onnx").touch()
    (tmp_path / "sherpa-onnx-whisper-large-v3" / "large-v3-tokens.txt").touch()
    (tmp_path / "sherpa-onnx-pyannote-segmentation-3-0").mkdir()
    (tmp_path / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").touch()
    (tmp_path / "emb.onnx").touch()
    (tmp_path / "silero_vad.onnx").touch()
    assert models_available(str(tmp_path))


def test_transcribe_raises_asr_provider_failed_when_models_missing(tmp_path):
    from app.domain.errors import AsrProviderFailed
    from app.domain.models import AudioAsset
    from app.providers.sherpa_onnx_asr import SherpaOnnxASRProvider

    provider = SherpaOnnxASRProvider(models_dir=str(tmp_path))
    asset = AudioAsset(
        id="a", encounter_id="e", kind="original", size_bytes=1, duration_seconds=1.0,
        created_at="2026-01-01T00:00:00+00:00",
    )
    with pytest.raises(AsrProviderFailed):
        provider.transcribe(asset)

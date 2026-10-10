"""Unit: scripts/check_vocab_leakage.py (tasks/11). Synthetic text only."""

import json

import pytest


@pytest.fixture()
def leakage(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import check_vocab_leakage

    return check_vocab_leakage


def test_sentence_examples_are_checked_short_term_names_are_not(leakage, tmp_path):
    (tmp_path / "f.json").write_text(json.dumps({"terms": [
        {"term": "TEE", "spoken_examples": ["내시경 초음파"]},
        {"term": "tandem gait", "spoken_examples": ["발을 붙여서 일자로 걸어 보세요"]},
    ]}, ensure_ascii=False))
    phrases = leakage.vocabulary_phrases(tmp_path)
    assert [ex for _f, ex in phrases] == ["발을 붙여서 일자로 걸어 보세요"]
    assert leakage.find_overlaps(phrases, "의사: 내시경 초음파 볼게요") == []
    assert leakage.find_overlaps(phrases, "의사: 발을 붙여서  일자로걸어 보세요.") == [("f.json", "발을 붙여서 일자로 걸어 보세요")]


def test_repo_vocabulary_has_sentence_phrases_to_check(leakage):
    assert len(leakage.vocabulary_phrases()) > 50


def test_prompt_quotes_are_checked_from_four_hangul(leakage, tmp_path):
    (tmp_path / "p.md").write_text('예: "재워놨어요"는 원문대로, "네"는 무시, "abc def"도 무시', encoding="utf-8")
    phrases = leakage.prompt_phrases(tmp_path)
    assert [q for _f, q in phrases] == ["재워놨어요"]
    assert leakage.find_overlaps(phrases, "의사: 항발작제를 넣고 재워놨어요") == [("p.md", "재워놨어요")]

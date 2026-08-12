"""置信度评分单元测试"""

from __future__ import annotations

import pytest

from src.chapters.constants import ChapterConfig
from src.chapters.models import ChapterCandidate, ChapterLevel
from src.chapters.scoring import score_candidates


def _candidate(
    level: ChapterLevel = ChapterLevel.CHAPTER,
    *,
    display_title: str = "章节标题甲",
    label: str = "第一章",
    number: int | None = 1,
    start_char: int = 0,
) -> ChapterCandidate:
    return ChapterCandidate(
        level=level,
        title=label,
        label=label,
        display_title=display_title,
        display_index_label="第1章",
        number=number,
        start_char=start_char,
        body_start_char=start_char + 10,
    )


def _scored(candidates: list[ChapterCandidate], config: ChapterConfig | None = None) -> list[ChapterCandidate]:
    return score_candidates(candidates, config)


def test_normal_title_gets_normal_score() -> None:
    candidates = _scored([_candidate()])
    assert candidates[0].confidence == pytest.approx(1.0 * 1.1)


def test_short_title_penalty() -> None:
    candidates = _scored([_candidate(display_title="短")])
    assert candidates[0].confidence == pytest.approx(1.0 * 0.8)


def test_long_title_penalty() -> None:
    candidates = _scored([_candidate(display_title="长" * 101)])
    assert candidates[0].confidence == pytest.approx(1.0 * 0.9)


def test_no_leading_word_penalty_for_chinese_numeral_without_第() -> None:
    candidates = _scored([_candidate(label="一章", display_title="章节标题甲")])
    assert candidates[0].confidence == pytest.approx(1.0 * 1.1 * 0.5)


def test_no_penalty_for_arabic_number_without_第() -> None:
    candidates = _scored([_candidate(label="1章", display_title="章节标题甲")])
    assert candidates[0].confidence == pytest.approx(1.0 * 1.1)


def test_volume_not_subject_to_strictness_penalty() -> None:
    candidates = _scored([_candidate(ChapterLevel.VOLUME, label="一卷", display_title="章节标题甲")])
    assert candidates[0].confidence == pytest.approx(1.0 * 1.1)


def test_filler_prefix_penalty() -> None:
    candidates = _scored([_candidate(display_title="的了是标题")])
    assert candidates[0].confidence == pytest.approx(1.0 * 1.1 * 0.4)


def test_number_increment_bonus() -> None:
    first = _candidate(display_title="章节标题甲", start_char=0)
    second = _candidate(display_title="章节标题乙", number=2, start_char=100)
    _scored([first, second])
    assert second.confidence == pytest.approx(1.0 * 1.1 * 1.1)


def test_number_decrement_penalty() -> None:
    first = _candidate(display_title="章节标题乙", number=2, start_char=0)
    second = _candidate(display_title="章节标题甲", number=1, start_char=100)
    _scored([first, second])
    assert second.confidence == pytest.approx(1.0 * 1.1 * 0.8)


def test_even_density_bonus() -> None:
    candidates = [
        _candidate(display_title=f"章节标题{i}", number=i, start_char=i * 100) for i in range(1, 4)
    ]
    scored = _scored(candidates)
    assert scored[0].confidence == pytest.approx(1.0 * 1.1 * 1.2)
    assert scored[1].confidence == pytest.approx(1.0 * 1.1 * 1.1 * 1.2)
    assert scored[2].confidence == pytest.approx(1.0 * 1.1 * 1.1 * 1.2)


def test_irregular_density_penalty() -> None:
    candidates = [
        _candidate(display_title="章节标题甲", number=1, start_char=0),
        _candidate(display_title="章节标题乙", number=2, start_char=10),
        _candidate(display_title="章节标题丙", number=3, start_char=20),
        _candidate(display_title="章节标题丁", number=4, start_char=5000),
    ]
    scored = _scored(candidates)
    assert scored[0].confidence == pytest.approx(1.0 * 1.1 * 0.8)


def test_fewer_than_three_same_level_no_density_factor() -> None:
    candidates = [
        _candidate(display_title="章节标题甲", number=1, start_char=0),
        _candidate(display_title="章节标题乙", number=2, start_char=100),
    ]
    scored = _scored(candidates)
    assert scored[1].confidence == pytest.approx(1.0 * 1.1 * 1.1)

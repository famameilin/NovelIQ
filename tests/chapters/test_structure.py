"""结构决策单元测试：过滤、空章节、开篇序言、自动分章兜底、finalize"""

from __future__ import annotations

from unittest.mock import patch

from src.chapters.constants import ChapterConfig
from src.chapters.models import ChapterCandidate, ChapterData, ChapterLevel
from src.chapters.structure import auto_split, decide_structure, finalize, guess_preliminary_title


def _candidate(
    level: ChapterLevel = ChapterLevel.CHAPTER,
    *,
    title: str = "第一章 起点",
    display_title: str = "起点",
    number: int | None = 1,
    start_char: int,
    body_start_char: int | None = None,
    confidence: float = 1.0,
) -> ChapterCandidate:
    return ChapterCandidate(
        level=level,
        title=title,
        label=title.split(" ")[0],
        display_title=display_title,
        display_index_label="第1章",
        number=number,
        start_char=start_char,
        body_start_char=body_start_char if body_start_char is not None else start_char + len(title),
        confidence=confidence,
    )


def _decide(text: str, candidates: list[ChapterCandidate], prologue_start: int = 0) -> list[ChapterData]:
    return decide_structure(text, candidates, prologue_start)


def test_filters_below_threshold() -> None:
    text = "第一章 起点\n内容。\n第二章 入城\n内容。"
    candidates = [
        _candidate(start_char=0, confidence=0.4),
        _candidate(title="第二章 入城", display_title="入城", number=2, start_char=12, confidence=0.9),
    ]
    chapters = _decide(text, candidates, prologue_start=18)
    assert [ch.title for ch in chapters] == ["第二章 入城"]


def test_single_qualifying_candidate_produces_chapter() -> None:
    text = "第一章 起点\n内容。"
    candidates = [_candidate(start_char=0, confidence=0.9)]
    chapters = _decide(text, candidates)
    assert len(chapters) == 1
    assert chapters[0].title == "第一章 起点"


def test_empty_chapter_kept_in_catalog_with_warning() -> None:
    text = "第七章\nxxxx\n第八章\n第九章\nyyyy"
    candidates = [
        _candidate(title="第七章", display_title="", number=7, start_char=0),
        _candidate(title="第八章", display_title="", number=8, start_char=9),
        _candidate(title="第九章", display_title="", number=9, start_char=13),
    ]
    with patch("src.chapters.structure.logger.warning") as mock_warning:
        chapters = _decide(text, candidates)
    assert [ch.title for ch in chapters] == ["第七章", "第八章", "第九章"]
    assert any("第八章" in str(call.args) for call in mock_warning.call_args_list)


def test_all_empty_chapters_fall_back() -> None:
    text = "第一章\n第二章\n第三章"
    candidates = [
        _candidate(title="第一章", display_title="", number=1, start_char=0),
        _candidate(title="第二章", display_title="", number=2, start_char=4),
        _candidate(title="第三章", display_title="", number=3, start_char=8),
    ]
    assert _decide(text, candidates) == []


def test_trailing_empty_chapter_dropped() -> None:
    """文末零长度章节（预告/断章残留）应从目录移除"""
    text = "第七章\nxxxx\n第八章"
    candidates = [
        _candidate(title="第七章", display_title="", number=7, start_char=0),
        _candidate(title="第八章", display_title="", number=8, start_char=9),
    ]
    chapters = _decide(text, candidates)
    assert [ch.title for ch in chapters] == ["第七章"]


def test_middle_empty_chapter_kept_in_catalog() -> None:
    """中间的空章节（连载缺章）仍保留目录条目"""
    text = "第六章\nxxxx\n第七章\n\n第八章\nyyyy"
    candidates = [
        _candidate(title="第六章", display_title="", number=6, start_char=0),
        _candidate(title="第七章", display_title="", number=7, start_char=9),
        _candidate(title="第八章", display_title="", number=8, start_char=18),
    ]
    chapters = _decide(text, candidates)
    assert [ch.title for ch in chapters] == ["第六章", "第七章", "第八章"]


def test_leading_named_volume_no_fake_prologue() -> None:
    """开篇为纯名称卷时不应产生假「序言」前置章节"""
    text = "少年篇\n第一章 起点\n内容甲。"
    candidates = [
        _candidate(level=ChapterLevel.ESSAY, title="少年篇", display_title="少年篇", number=None, start_char=0),
        _candidate(title="第一章 起点", display_title="起点", number=1, start_char=4),
    ]
    chapters = _decide(text, candidates)
    assert [ch.level for ch in chapters] == [ChapterLevel.ESSAY, ChapterLevel.CHAPTER]
    assert [ch.title for ch in chapters] == ["少年篇", "第一章 起点"]
    assert text[chapters[1].start_char : chapters[1].end_char].strip() == "内容甲。"


def test_body_ranges_between_adjacent_candidates() -> None:
    text = "第一章 起点\n内容甲。\n第二章 入城\n内容乙。"
    candidates = [
        _candidate(start_char=0),
        _candidate(title="第二章 入城", display_title="入城", number=2, start_char=12),
    ]
    chapters = _decide(text, candidates)
    assert len(chapters) == 2
    assert text[chapters[0].start_char : chapters[0].end_char].strip() == "内容甲。"
    assert text[chapters[1].start_char : chapters[1].end_char].strip() == "内容乙。"


def test_prologue_inserted_when_leading_text_large_enough() -> None:
    text = "这段开篇正文足够长，超过了最小阈值。\n第一章 起点\n内容甲。"
    candidates = [_candidate(start_char=20)]
    chapters = _decide(text, candidates)
    assert len(chapters) == 2
    assert chapters[0].level == ChapterLevel.PREFACE
    assert chapters[0].title == "序言"
    assert chapters[1].level == ChapterLevel.CHAPTER


def test_prologue_guesses_preliminary_title() -> None:
    text = "楔子 命运\n他站在山巅。\n第一章 起点\n内容甲。"
    candidates = [_candidate(start_char=12)]
    chapters = _decide(text, candidates)
    assert chapters[0].title == "楔子"


def test_preliminary_title_rejects_body_paragraph_lines() -> None:
    """2026-08-13 P2 用于验证正文段落首行以开篇词开头（如「引言：本书讲述了……」）
    不再被误判为开篇标题（标题形态约束：剩余内容含句末标点即拒绝）"""
    assert guess_preliminary_title("引言：本书讲述了整个故事。\n正文继续……") is None
    assert guess_preliminary_title("尾声临近，众人收拾行装。") is None
    # 纯标题形态仍可识别（含短标题内容或为空）
    assert guess_preliminary_title("楔子\n正文开始。") == "楔子"
    assert guess_preliminary_title("序章 命运的开端\n正文开始。") == "序章"


def test_prologue_does_not_swallow_first_chapter_title_line() -> None:
    """2026-08-12 用于验证序言区间截止于第一章标题行之前，标题行不属于任何 chunk"""
    text = "楔子 命运\n这段开篇正文足够长，超过了最小阈值。\n第一章 起点\n内容甲。"
    first_title_start = text.index("第一章 起点")
    body_start = text.index("内容甲。")
    candidates = [_candidate(start_char=first_title_start, body_start_char=body_start)]
    chapters = _decide(text, candidates)
    assert len(chapters) == 2
    prologue, first = chapters
    assert prologue.level == ChapterLevel.PREFACE
    assert prologue.title == "楔子"
    # 序言 chunk 止于第一章标题行之前，不含标题
    assert prologue.end_char == first_title_start
    assert text[prologue.start_char : prologue.end_char].strip().startswith("楔子")
    assert "第一章" not in text[prologue.start_char : prologue.end_char]
    # 第一章 chunk 从正文起点开始，含正文且不含标题行
    assert first.title_start_char == first_title_start
    assert first.start_char == body_start
    assert text[first.start_char : first.end_char].strip() == "内容甲。"
    assert "第一章" not in text[first.start_char : first.end_char]


def test_prologue_not_inserted_when_too_short() -> None:
    text = "序\n第一章 起点\n内容甲。"
    candidates = [_candidate(start_char=2)]
    assert len(_decide(text, candidates)) == 1


def test_prologue_excludes_toc_page_text() -> None:
    text = "目录\n第一章 起点 1\n\n长开篇内容，超过十个字符。\n第一章 起点\n内容甲。"
    candidates = [_candidate(start_char=29)]
    chapters = _decide(text, candidates, prologue_start=12)
    assert len(chapters) == 2
    assert chapters[0].level == ChapterLevel.PREFACE
    prologue_body = text[chapters[0].start_char : chapters[0].end_char]
    assert "目录" not in prologue_body
    assert "长开篇内容" in prologue_body


def test_guess_preliminary_title() -> None:
    assert guess_preliminary_title("楔子 命运") == "楔子"
    assert guess_preliminary_title("序章 开始") == "序章"
    assert guess_preliminary_title("Prologue") == "Prologue"
    assert guess_preliminary_title("普通开篇文字") is None


def test_auto_split_single_chunk_when_short() -> None:
    chapters = auto_split("短文本。", ChapterConfig())
    assert len(chapters) == 1
    assert chapters[0].level == ChapterLevel.AUTO
    assert chapters[0].title == "自动分章"


def test_auto_split_splits_at_paragraph_boundaries() -> None:
    config = ChapterConfig()
    text = "\n\n".join(["甲" * 600] * 4)
    chapters = auto_split(text, config)
    assert len(chapters) > 1
    for chapter in chapters:
        assert chapter.end_char - chapter.start_char <= config.fallback_chunk_size


def test_auto_split_splits_without_paragraph_boundaries() -> None:
    config = ChapterConfig()
    text = "字。" * 1200
    chapters = auto_split(text, config)
    assert len(chapters) > 1
    for chapter in chapters:
        assert len(text[chapter.start_char : chapter.end_char].strip()) <= config.fallback_chunk_size


def test_finalize_assigns_ids_and_clamps() -> None:
    text = "第一章 起点\n内容甲。\n第二章 入城\n内容乙。"
    candidates = [
        _candidate(start_char=0),
        _candidate(title="第二章 入城", display_title="入城", number=2, start_char=12),
    ]
    chapters = finalize(text, _decide(text, candidates))
    assert [(ch.chapter_id, ch.sequence) for ch in chapters] == [(1, 1), (2, 2)]
    assert all(ch.start_char <= ch.end_char for ch in chapters)

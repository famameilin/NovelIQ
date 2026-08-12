"""TOC 目录页识别单元测试"""

from __future__ import annotations

from src.chapters.toc import detect_toc_range


def test_detects_toc_page() -> None:
    text = "目录\n第一章 起点 1\n第二章 入城 5\n第三章 拜师 9\n\n第一章 起点\n内容。"
    toc = detect_toc_range(text)
    assert toc is not None
    start, end = toc
    assert text[start : start + 2] == "目录"
    assert "起点 9" not in text[start:end]


def test_toc_without_page_numbers() -> None:
    text = "目 录\n第一章 起点\n第二章 入城\n\n正文开始\n内容。"
    toc = detect_toc_range(text)
    assert toc is not None
    assert text[toc[0] : toc[1]].startswith("目 录")


def test_toc_title_with_colon() -> None:
    text = "目录：\n第一章 起点 1\n第二章 入城 2\n\n正文"
    assert detect_toc_range(text) is not None


def test_single_entry_not_toc() -> None:
    text = "目录\n第一章 起点 1\n\n正文\n内容。"
    assert detect_toc_range(text) is None


def test_no_title_line_not_toc() -> None:
    text = "第一章 起点\n第二章 入城\n内容。"
    assert detect_toc_range(text) is None


def test_title_line_too_far_not_toc() -> None:
    text = ("正文" * 50) + "\n目录\n第一章 起点 1\n第二章 入城 2\n\n内容。"
    assert detect_toc_range(text) is None


def test_disabled_toc() -> None:
    from src.chapters.constants import ChapterConfig

    config = ChapterConfig()
    config.toc_enabled = False
    text = "目录\n第一章 起点 1\n第二章 入城 5\n\n内容。"
    assert detect_toc_range(text, config) is None


def test_empty_text() -> None:
    assert detect_toc_range("") is None


def test_toc_without_blank_line_does_not_swallow_real_chapter_title() -> None:
    """
    2026-08-12 用于验证目录与正文之间无空行时：
    正文首个真实章节标题（与目录条目同名）不被吞进目录范围。
    """
    text = "目录\n第一章 起点 1\n第二章 入城 5\n第一章 起点\n林渡走在街头。"
    toc = detect_toc_range(text)
    assert toc is not None
    start, end = toc
    # 目录范围只覆盖前两条目录条目，正文真实标题行保留在范围内外
    assert text[start:end].count("第一章") == 1
    assert "林渡走在街头" not in text[start:end]


def test_toc_without_blank_line_keeps_entries_with_page_numbers() -> None:
    """
    2026-08-12 用于验证带页码的目录条目去页码归一化后
    与正文同名标题区分：正文标题行作为目录页结束边界。
    """
    text = "目录\n第一章 起点 1\n第二章 入城 5\n第三章 拜师 9\n第一章 起点\n林渡走在街头。"
    toc = detect_toc_range(text)
    assert toc is not None
    start, end = toc
    assert text[start:end].count("第三章") == 1
    assert "林渡走在街头" not in text[start:end]


def test_toc_with_volume_entries_after_number() -> None:
    """2026-08-12 用于验证「卷一/第2卷」形态的卷条目被目录识别（假章节带页码不进入正文）"""
    text = "目录\n卷一 风起 1\n卷二 云涌 9\n第三章 入城 1\n\n正文内容。"
    toc = detect_toc_range(text)
    assert toc is not None
    start, end = toc
    assert text[start:end].count("卷一") == 1
    assert "正文内容" not in text[start:end]


def test_toc_with_chinese_volume_numerals() -> None:
    """2026-08-12 用于验证「卷上/卷中」形态的卷条目被目录识别"""
    text = "目录\n卷上 少年 1\n卷中 江湖 5\n卷下 风云 9\n\n正文内容。"
    assert detect_toc_range(text) is not None


def test_toc_with_english_entries() -> None:
    """2026-08-12 用于验证 Chapter/Unit/Volume/Part 英文编号条目被目录识别"""
    text = "目录\nChapter 1 起点 1\nChapter 2 入城 5\nUnit 1 风起 1\n\n正文内容。"
    toc = detect_toc_range(text)
    assert toc is not None
    start, end = toc
    assert text[start:end].count("Chapter 1") == 1
    assert "正文内容" not in text[start:end]

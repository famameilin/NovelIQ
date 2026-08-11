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

"""章节解析预处理单元测试"""

from __future__ import annotations

from src.chapters.preprocess import preprocess_text


def test_strips_bom() -> None:
    assert preprocess_text("\ufeff第一章 起点") == "第一章 起点"


def test_normalizes_crlf_and_cr() -> None:
    assert preprocess_text("a\r\nb\rc") == "a\nb\nc"


def test_normalizes_line_separators() -> None:
    assert preprocess_text("a\u2028b\u2029c") == "a\nb\nc"


def test_removes_zero_width_chars() -> None:
    assert preprocess_text("a\u200bb\u200cc\u200dd") == "abcd"


def test_replaces_full_width_space() -> None:
    assert preprocess_text("a\u3000b") == "a b"


def test_collapses_three_plus_blank_lines_to_two() -> None:
    assert preprocess_text("a\n\n\n\nb") == "a\n\nb"


def test_two_blank_lines_unchanged() -> None:
    assert preprocess_text("a\n\nb") == "a\n\nb"


def test_blank_line_with_spaces_collapsed() -> None:
    assert preprocess_text("a\n \n\nb") == "a\n\nb"


def test_empty_and_whitespace_only() -> None:
    assert preprocess_text("") == ""
    assert preprocess_text("   ") == "   "


def test_preprocess_is_idempotent() -> None:
    text = "\ufeff第一段\r\n第二段\u200b\n\n\n第三段\u2028"
    once = preprocess_text(text)
    twice = preprocess_text(once)
    assert once == twice

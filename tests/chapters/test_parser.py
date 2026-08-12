"""章节解析端到端单元测试"""

from __future__ import annotations

from src.chapters.constants import ChapterConfig
from src.chapters.models import ChapterLevel
from src.chapters.parser import parse_chapters


def test_standard_chapter_format() -> None:
    text = "第一章 起点\n内容甲。\n第二章 入城\n内容乙。\n第三章 拜师\n内容丙。"
    chapters = parse_chapters(text)
    assert [ch.title for ch in chapters] == ["第一章 起点", "第二章 入城", "第三章 拜师"]
    assert [ch.display_title for ch in chapters] == ["起点", "入城", "拜师"]
    assert [ch.display_index_label for ch in chapters] == ["第1章", "第2章", "第3章"]
    assert [ch.chapter_id for ch in chapters] == [1, 2, 3]


def test_arabic_and_english_formats() -> None:
    text = "第1章 开始\n内容甲。\nChapter 2 继续\n内容乙。"
    chapters = parse_chapters(text)
    assert [ch.level for ch in chapters] == [ChapterLevel.CHAPTER, ChapterLevel.CHAPTER]
    assert [ch.display_title for ch in chapters] == ["开始", "继续"]


def test_mixed_hierarchy_flat_output() -> None:
    text = "第一部 风起\n第一章 少年\n内容甲。\n第二章 拜师\n内容乙。\n第一回 回目\n内容丙。"
    chapters = parse_chapters(text)
    levels = [ch.level for ch in chapters]
    assert ChapterLevel.PART in levels
    assert ChapterLevel.CHAPTER in levels
    assert ChapterLevel.HUI in levels
    ids = [ch.chapter_id for ch in chapters]
    assert ids == list(range(1, len(chapters) + 1))


def test_extra_types_standalone() -> None:
    text = "第一章 起点\n内容甲。\n番外 前传\n内容乙。\n后记\n内容丙。"
    chapters = parse_chapters(text)
    assert [ch.level for ch in chapters] == [
        ChapterLevel.CHAPTER,
        ChapterLevel.EXTRA,
        ChapterLevel.EXTRA,
    ]
    assert all(ch.display_index_label is None for ch in chapters if ch.level == ChapterLevel.EXTRA)


def test_prologue_inserted_when_leading_body_exists() -> None:
    # 开篇正文须严格超过 prologue_min_chars（标题行不参与序言长度计算）
    text = "这个开篇故事足够长了。\n第一章 起点\n内容甲。\n第二章 入城\n内容乙。"
    chapters = parse_chapters(text)
    assert chapters[0].level == ChapterLevel.PREFACE
    assert chapters[0].title == "序言"


def test_no_structure_falls_back_to_auto_split() -> None:
    text = "没有任何章节标题的文本。" * 300
    chapters = parse_chapters(text)
    assert len(chapters) > 1
    assert all(ch.level == ChapterLevel.AUTO for ch in chapters)
    assert all(ch.title == "自动分章" for ch in chapters)


def test_short_chapterless_text_single_auto_chapter() -> None:
    chapters = parse_chapters("短文本，没有章节。")
    assert len(chapters) == 1
    assert chapters[0].level == ChapterLevel.AUTO


def test_toc_page_skipped() -> None:
    text = "目录\n第一章 起点 1\n第二章 入城 5\n第三章 拜师 9\n\n第一章 起点\n内容甲。\n第二章 入城\n内容乙。"
    chapters = parse_chapters(text)
    assert [ch.title for ch in chapters] == ["第一章 起点", "第二章 入城"]
    assert [ch.start_char for ch in chapters] == [37, 49]


def test_bom_and_crlf_handled() -> None:
    text = "\ufeff第一章 起点\r\n内容甲。\r\n第二章 入城\r\n内容乙。"
    chapters = parse_chapters(text)
    assert len(chapters) == 2
    assert chapters[0].title == "第一章 起点"


def test_duplicate_titles_keep_distinct_ids() -> None:
    text = "第1章 序章\n甲。\n第2章 中段\n乙。\n第1章 序章\n丙。"
    chapters = parse_chapters(text)
    assert [ch.chapter_id for ch in chapters] == [1, 2, 3]
    assert chapters[0].title == chapters[2].title


def test_empty_chapter_skipped_in_body_but_kept_in_catalog() -> None:
    text = "第七章\nxxxx\n第八章\n第九章\nyyyy"
    chapters = parse_chapters(text)
    assert [ch.title for ch in chapters] == ["第七章", "第八章", "第九章"]
    body = [text[ch.start_char : ch.end_char].strip() for ch in chapters]
    assert body[1] == ""


def test_body_noise_filtered_by_confidence() -> None:
    text = "第一章 起点\n内容甲。\n第二章 入城\n内容乙。\n正文行：第一章的事件发生在傍晚\n第三章 拜师\n内容丙。"
    chapters = parse_chapters(text)
    assert [ch.title for ch in chapters] == ["第一章 起点", "第二章 入城", "第三章 拜师"]


def test_custom_config_fallback_chunk_size() -> None:
    config = ChapterConfig()
    config.fallback_chunk_size = 100
    text = "没有章节的文本。" * 50
    chapters = parse_chapters(text, config)
    assert all(ch.end_char - ch.start_char <= 100 for ch in chapters)


def test_custom_config_disabled_toc() -> None:
    config = ChapterConfig()
    config.toc_enabled = False
    text = "目录\n第一章 起点 1\n第二章 入城 5\n\n第一章 起点\n内容甲。\n第二章 入城\n内容乙。"
    chapters = parse_chapters(text, config)
    assert len(chapters) >= 4

"""候选收集单元测试：各层级正则、编号/标题提取、正文起点、去重"""

from __future__ import annotations

from src.chapters.candidates import collect_candidates
from src.chapters.models import ChapterLevel


def _single(text: str, level: ChapterLevel) -> object:
    candidates = collect_candidates(text)
    matched = [c for c in candidates if c.level == level]
    assert len(matched) == 1, [c.title for c in candidates]
    return matched[0]


def test_part_regex() -> None:
    candidate = _single("第一部 风云再起\n内容", ChapterLevel.PART)
    assert candidate.display_title == "风云再起"
    assert candidate.display_index_label == "第1部"
    assert candidate.number == 1


def test_part_regex_upper_middle_lower() -> None:
    for title in ("上部", "中部", "下部"):
        _single(f"{title}\n内容", ChapterLevel.PART)


def test_volume_regex_forms() -> None:
    for title in ("第一卷", "卷一", "Unit 3"):
        candidate = _single(f"{title} 名称\n内容", ChapterLevel.VOLUME)
        assert candidate.number is not None


def test_volume_positional_form_no_number() -> None:
    """卷上/卷中/卷下 为方位表达，无编号"""
    candidate = _single("卷上 名称\n内容", ChapterLevel.VOLUME)
    assert candidate.number is None


def test_volume_english_regex() -> None:
    candidate = _single("Volume 2 名称\n内容", ChapterLevel.VOLUME)
    assert candidate.number == 2
    assert candidate.display_index_label == "第2卷"


def test_chapter_regex_forms() -> None:
    for title in ("第一章", "第1章", "1章", "Chapter 5", "第〇章", "第两章"):
        candidate = _single(f"{title} 名称\n内容", ChapterLevel.CHAPTER)
        assert candidate.number is not None


def test_chapter_display_fields() -> None:
    candidate = _single("第一章 起点\n内容", ChapterLevel.CHAPTER)
    assert candidate.display_title == "起点"
    assert candidate.display_index_label == "第1章"
    assert candidate.title == "第一章 起点"


def test_section_regex() -> None:
    _single("第一节 场景\n内容", ChapterLevel.SECTION)
    _single("第一小节\n内容", ChapterLevel.SECTION)


def test_hui_regex() -> None:
    candidate = _single("第一回 风起\n内容", ChapterLevel.HUI)
    assert candidate.display_index_label == "第1回"


def test_essay_regex() -> None:
    _single("第一篇 楔子\n内容", ChapterLevel.ESSAY)
    candidate = _single("Part 2 后章\n内容", ChapterLevel.ESSAY)
    assert candidate.number == 2


def test_extra_regex_types() -> None:
    for title in ("番外", "后记", "尾声", "彩蛋", "外传", "附录", "特别篇", "终章", "结语"):
        candidate = _single(f"{title} 名称\n内容", ChapterLevel.EXTRA)
        assert candidate.display_index_label is None


def test_extra_with_number() -> None:
    candidate = _single("番外一 前传\n内容", ChapterLevel.EXTRA)
    assert candidate.number == 1


def test_plain_chinese_number_line_not_matched() -> None:
    """纯数字行/罗马数字不支持（与参考实现一致）"""
    candidates = collect_candidates("1\n内容\n001\n内容\nI\n内容")
    assert candidates == []


def test_body_noise_line_not_collected() -> None:
    candidates = collect_candidates("正文中提到第一章但不以标题开头\n内容")
    assert candidates == []


def test_title_body_same_line_fix() -> None:
    text = "第一章 起点 他是个少年，热爱冒险……\n第二章 入城\n内容"
    candidates = collect_candidates(text)
    chapter = next(c for c in candidates if c.level == ChapterLevel.CHAPTER)
    assert chapter.start_char == 0
    body_start = chapter.body_start_char
    assert text[body_start : body_start + 2] == "他是"


def test_short_title_no_same_line_fix() -> None:
    text = "第一章 起点\n内容"
    candidate = collect_candidates(text)[0]
    assert candidate.body_start_char == text.find("\n")
    assert candidate.display_title == "起点"


def test_same_line_dedup_keeps_higher_priority() -> None:
    text = "第一章 内容\n正文"
    candidates = collect_candidates(text)
    assert len(candidates) == 1
    assert candidates[0].level == ChapterLevel.CHAPTER


def test_candidates_sorted_by_position() -> None:
    text = "第一章 甲\n内容\n第三章 丙\n内容\n第二章 乙\n内容"
    candidates = collect_candidates(text)
    starts = [c.start_char for c in candidates]
    assert starts == sorted(starts)


def test_skip_range_excludes_candidates() -> None:
    text = "第一章 甲\n第二章 乙\n内容"
    candidates = collect_candidates(text, skip_range=(0, 5))
    assert [c.title for c in candidates] == ["第二章 乙"]


def test_named_essay_without_number() -> None:
    """纯名称卷（少年篇/风起篇）应识别为 ESSAY 候选"""
    candidate = _single("少年篇\n第一章 起点\n内容", ChapterLevel.ESSAY)
    assert candidate.display_title == "少年篇"
    assert candidate.number is None
    assert candidate.display_index_label is None


def test_named_volume_without_number() -> None:
    candidate = _single("风起卷\n第一章 起点\n内容", ChapterLevel.VOLUME)
    assert candidate.display_title == "风起卷"
    assert candidate.number is None


def test_named_part_without_number() -> None:
    _single("上部\n第一章 起点\n内容", ChapterLevel.PART)


def test_numbered_essay_prefers_numbered_regex() -> None:
    """带编号的篇仍命中编号正则（优先级高于纯名称卷）"""
    candidate = _single("第一篇 楔子\n内容", ChapterLevel.ESSAY)
    assert candidate.display_index_label == "第1篇"


def test_named_volume_line_with_trailing_space() -> None:
    _single("少年篇 \n第一章 起点\n内容", ChapterLevel.ESSAY)


def test_body_line_not_matched_as_named_volume() -> None:
    """正文行不以 篇/卷/部 结尾时不误报"""
    candidates = collect_candidates("他翻开了书卷\n内容")
    assert candidates == []

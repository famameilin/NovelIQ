"""重复版本守卫单元测试：同号同题折叠、内容不相似保留、短正文豁免、端到端解析"""

from __future__ import annotations

import re

from src.utils.chapters.constants import ChapterConfig
from src.utils.chapters.models import ChapterData, ChapterLevel
from src.utils.chapters.parser import parse_chapters
from src.utils.chapters.revisions import drop_duplicate_revisions

_CORE = "西郊猎场的晨雾还未散去，猎队已经列队出发。" * 15
_OLD_ENDING = "旧稿独有的结尾，火光一闪而熄。" * 2
_EXPANSION = "扩写版本新增的过渡段落。" * 4
_NEW_ENDING = "定稿独有的结尾，猴子按着刀柄。" * 2

_LABEL_PREFIX = re.compile(r"^第[一二三四五六七八九十百零]+章\s*")


def _build(spec: list[tuple[int | None, str, str]]) -> tuple[str, list[ChapterData]]:
    """按 (编号, 标题行, 正文) 构造与正文偏移一致的 (text, chapters)"""
    text = ""
    chapters: list[ChapterData] = []
    for number, title, body in spec:
        title_start = len(text)
        text += title + "\n" + body
        chapters.append(
            ChapterData(
                chapter_id=0,
                sequence=0,
                level=ChapterLevel.CHAPTER,
                title=title,
                display_title=_LABEL_PREFIX.sub("", title),
                display_index_label=None,
                number=number,
                title_start_char=title_start,
                start_char=title_start + len(title) + 1,
                end_char=len(text),
            )
        )
    return text, chapters


def test_duplicate_revision_keeps_longer_version() -> None:
    text, chapters = _build(
        [
            (18, "第十八章 暗算从来不挑时", _CORE + _EXPANSION),
            (19, "第十九章 西郊猎场暗流涌", _CORE + _OLD_ENDING),
            (19, "第十九章 西郊猎场暗流涌", _CORE + _EXPANSION + _NEW_ENDING),
            (20, "第二十章 古战场中见真性", _CORE + _EXPANSION),
        ]
    )
    kept = drop_duplicate_revisions(text, chapters)
    assert [chapter.number for chapter in kept] == [18, 19, 20]
    assert kept[1].start_char == chapters[2].start_char
    assert _NEW_ENDING in text[kept[1].start_char : kept[1].end_char]
    assert _OLD_ENDING not in text[kept[1].start_char : kept[1].end_char]


def test_dissimilar_same_number_chapters_both_kept() -> None:
    short_body = _CORE + _OLD_ENDING
    different_core = "朱雀大街的人潮从早到晚都没有停歇的意思。" * 8
    long_body = different_core + "另一条故事线的独有内容与猎场毫无交集。" * 6
    text, chapters = _build(
        [
            (19, "第十九章 西郊猎场暗流涌", short_body),
            (19, "第十九章 西郊猎场暗流涌", long_body),
        ]
    )
    kept = drop_duplicate_revisions(text, chapters)
    assert len(kept) == 2


def test_below_threshold_containment_keeps_both() -> None:
    core = "共同的开头铺垫。" * 8
    # 尾部字符集与核心及彼此完全不相交，包含率确定性地等于 core 占比：64/304 ≈ 0.21
    tail_a = "甲乙丙丁戊己庚辛壬癸！" * 24
    tail_b = "子丑寅卯辰巳午未申酉！" * 24
    text, chapters = _build(
        [
            (2, "第二章 猎场", core + tail_a),
            (2, "第二章 猎场", core + tail_b),
        ]
    )
    kept = drop_duplicate_revisions(text, chapters)
    assert len(kept) == 2


def test_same_title_different_numbers_both_kept() -> None:
    body = _CORE + _EXPANSION
    text, chapters = _build(
        [
            (1, "第一章 猎场", body),
            (2, "第二章 猎场", body),
        ]
    )
    kept = drop_duplicate_revisions(text, chapters)
    assert len(kept) == 2


def test_non_adjacent_same_number_not_collapsed() -> None:
    body = _CORE + _EXPANSION
    text, chapters = _build(
        [
            (19, "第十九章 西郊猎场暗流涌", body),
            (20, "第二十章 古战场中见真性", body),
            (19, "第十九章 西郊猎场暗流涌", body),
        ]
    )
    kept = drop_duplicate_revisions(text, chapters)
    assert len(kept) == 3


def test_chain_of_revisions_keeps_longest() -> None:
    text, chapters = _build(
        [
            (19, "第十九章 西郊猎场暗流涌", _CORE + _OLD_ENDING),
            (19, "第十九章 西郊猎场暗流涌", _CORE + _EXPANSION),
            (19, "第十九章 西郊猎场暗流涌", _CORE + _EXPANSION + _NEW_ENDING),
        ]
    )
    kept = drop_duplicate_revisions(text, chapters)
    assert len(kept) == 1
    assert _NEW_ENDING in text[kept[0].start_char : kept[0].end_char]
    assert _OLD_ENDING not in text[kept[0].start_char : kept[0].end_char]


def test_short_bodies_never_collapsed() -> None:
    body = "正文过短，不做内容比对。" * 3
    text, chapters = _build(
        [
            (19, "第十九章 西郊猎场暗流涌", body),
            (19, "第十九章 西郊猎场暗流涌", body),
        ]
    )
    kept = drop_duplicate_revisions(text, chapters)
    assert len(kept) == 2


def test_title_whitespace_normalized() -> None:
    text, chapters = _build(
        [
            (19, "第十九章 西郊 猎场暗流涌", _CORE + _OLD_ENDING),
            (19, "第十九章 西郊猎场暗流涌", _CORE + _EXPANSION + _NEW_ENDING),
        ]
    )
    assert chapters[0].display_title != chapters[1].display_title
    kept = drop_duplicate_revisions(text, chapters)
    assert len(kept) == 1


def test_equal_length_keeps_later() -> None:
    body = _CORE + _EXPANSION
    text, chapters = _build(
        [
            (19, "第十九章 西郊猎场暗流涌", body),
            (19, "第十九章 西郊猎场暗流涌", body),
        ]
    )
    kept = drop_duplicate_revisions(text, chapters)
    assert len(kept) == 1
    assert kept[0].start_char == chapters[1].start_char


def test_parse_chapters_collapses_duplicate_end_to_end() -> None:
    novel = (
        "第一章 起点\n"
        + _CORE
        + "\n"
        + "第二章 猎场\n"
        + _CORE
        + _OLD_ENDING
        + "\n"
        + "第二章 猎场\n"
        + _CORE
        + _EXPANSION
        + _NEW_ENDING
        + "\n"
        + "第三章 终局\n"
        + _CORE
    )
    chapters = parse_chapters(novel)
    assert [chapter.display_index_label for chapter in chapters] == ["第1章", "第2章", "第3章"]
    second = chapters[1]
    second_body = novel[second.start_char : second.end_char]
    assert _NEW_ENDING in second_body
    assert _OLD_ENDING not in second_body


def test_threshold_config_override() -> None:
    class _StrictConfig(ChapterConfig):
        revision_containment_threshold = 0.99

    text, chapters = _build(
        [
            (19, "第十九章 西郊猎场暗流涌", _CORE + _OLD_ENDING),
            (19, "第十九章 西郊猎场暗流涌", _CORE + _EXPANSION + _NEW_ENDING),
        ]
    )
    kept = drop_duplicate_revisions(text, chapters, _StrictConfig())
    assert len(kept) == 2

"""正式章节的段落坐标映射"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from src.fact_graph.inputs import ChapterParagraphInfo

from .errors import AnnotationInputError


class ChapterParagraphRow(Protocol):
    paragraph_id: int
    local_start_char: int
    local_end_char: int
    text: str


def build_chapter_paragraph_info(rows: Sequence[ChapterParagraphRow]) -> ChapterParagraphInfo:
    """按语义字段绑定本章段号与字符区间，禁止缺少原文事实源"""
    if not rows:
        raise AnnotationInputError("正式章节没有原文段落，无法构建段落映射")
    return ChapterParagraphInfo(
        paragraph_ids=[int(row.paragraph_id) for row in rows],
        char_spans=[(int(row.local_start_char), int(row.local_end_char)) for row in rows],
        texts=[str(row.text) for row in rows],
    )

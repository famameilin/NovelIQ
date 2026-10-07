"""当前工作产出的原文与段落归属校验"""

from __future__ import annotations

from src.agents.annotation.output_models import BoundChapterAnnotation
from src.fact_graph.inputs import ChapterParagraphInfo

from .errors import AnnotationInputError


def validate_bound_annotation(
    annotation: BoundChapterAnnotation,
    *,
    chapter_id: int,
    chapter_text: str,
    paragraph_info: ChapterParagraphInfo | None = None,
) -> None:
    """复核对话位置、逐字原文和自选段标签，避免保存越界产出"""
    if chapter_id <= 0:
        raise AnnotationInputError("chapter_id 必须为正整数")
    for dialogue in annotation.dialogues:
        if dialogue.end > len(chapter_text):
            raise ValueError(f"系统对话位置超出原文: chapter_id={chapter_id}")
        if chapter_text[dialogue.start : dialogue.end] != dialogue.content:
            raise ValueError(f"系统对话原文绑定不一致: chapter_id={chapter_id}")
    if paragraph_info is not None:
        known_paragraph_ids = set(paragraph_info.paragraph_ids)
        for label in annotation.paragraph_labels:
            if label.paragraph_id not in known_paragraph_ids:
                raise ValueError(
                    f"系统自选段标签超出本章段落范围: chapter_id={chapter_id} paragraph_id={label.paragraph_id}"
                )

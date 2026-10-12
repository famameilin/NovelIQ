"""按当前页面已授权的证据位置读取原文，不接受任意章节绕过截点"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import Chapter, Paragraph
from src.utils.identity import text_digest


def read_evidence_source(
    session: Session, run_id: str, evidence: list[dict[str, Any]], chapter_id: int | None = None
) -> dict[str, Any]:
    allowed = {item["chapter_id"] for item in evidence if "chapter_id" in item}
    if chapter_id is None:
        chapter_id = next((item["chapter_id"] for item in evidence if "chapter_id" in item), None)
    if chapter_id not in allowed:
        raise LookupError("SOURCE_NOT_FOUND")
    chapter = session.get(Chapter, (chapter_id, run_id))
    if chapter is None:
        raise LookupError("SOURCE_NOT_FOUND")
    paragraphs = list(
        session.scalars(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.paragraph_index)
        )
    )
    by_id = {paragraph.paragraph_id: paragraph for paragraph in paragraphs}
    for item in evidence:
        if item.get("chapter_id") != chapter_id or "paragraph_id" not in item:
            continue
        paragraph = by_id.get(item["paragraph_id"])
        if paragraph is None:
            raise ValueError("证据段落不属于来源章节")
        start, end = item.get("char_start", 0), item.get("char_end", len(paragraph.text))
        if not 0 <= start < end <= len(paragraph.text):
            raise ValueError("证据字符范围与原文不一致")
        if item.get("text_hash") and item["text_hash"] != text_digest(paragraph.text[start:end]):
            raise ValueError("证据文本校验不一致")
    return {
        "chapter_id": chapter_id,
        "title": chapter.display_title or chapter.title,
        "paragraphs": [
            {"paragraph_id": item.paragraph_id, "paragraph_index": item.paragraph_index, "text": item.text}
            for item in paragraphs
        ],
    }

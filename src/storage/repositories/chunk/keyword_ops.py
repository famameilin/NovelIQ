"""
chunk 关键词检索与原文读取

- search_paragraphs_by_keywords: rg 风格关键词子串精确匹配，直接扫 paragraphs 事实源
- fetch_chunk_text: 读取指定 chunk 的原文全文（read 工具的数据源）
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.storage.models import Chunk, Paragraph


@dataclass(frozen=True)
class KeywordMatchRow:
    """关键词检索段落 DTO，携带命中的关键词明细与全文定位"""

    paragraph_id: int
    chunk_id: int
    paragraph_index: int
    paragraph_text: str
    local_start_char: int
    local_end_char: int
    global_start_char: int
    global_end_char: int
    matched_keywords: tuple[str, ...]
    match_count: int


def search_paragraphs_by_keywords(
    session: Session,
    run_id: str,
    keywords: Sequence[str],
    top_k: int = 10,
    exclude_paragraph_ids: Sequence[int] | None = None,
    min_paragraph_id: int | None = None,
    max_paragraph_id: int | None = None,
) -> list[KeywordMatchRow]:
    """
    2026-08-14 二期段落化：直接扫 paragraphs 事实源（不再扫 chunks + Python 重切段），
    段落身份与 local/global 坐标一律取 paragraphs 持久化列；
    paragraphs.text 建有 lower(text) gin_trgm_ops 索引（idx_paragraphs_text_trgm）
    """
    # 2026-08-13 P2-6：词项统一小写（与 extract_query_terms 口径一致），
    # SQL 与 Python 两侧都以小写对比，避免英文词大小写不一致漏命中
    normalized = list(
        dict.fromkeys(kw.strip().lower() for kw in keywords if kw and kw.strip())
    )
    if not normalized:
        return []

    # 2026-08-13 P2-6：查询词项已由 extract_query_terms 统一小写，
    # SQL 侧对原文做 lower() 归一，避免 LIKE 大小写敏感导致英文词漏命中
    match_expressions = [
        func.lower(Paragraph.text).contains(keyword, autoescape=True)
        for keyword in normalized
    ]
    stmt = (
        select(
            Paragraph.paragraph_id,
            Paragraph.chunk_id,
            Paragraph.paragraph_index,
            Paragraph.text,
            Paragraph.local_start_char,
            Paragraph.local_end_char,
            Paragraph.global_start_char,
            Paragraph.global_end_char,
        )
        .where(
            Paragraph.run_id == run_id,
            or_(*match_expressions),
        )
        .order_by(Paragraph.paragraph_id.asc())
    )
    if exclude_paragraph_ids:
        stmt = stmt.where(Paragraph.paragraph_id.not_in(list(exclude_paragraph_ids)))
    if min_paragraph_id is not None:
        stmt = stmt.where(Paragraph.paragraph_id >= min_paragraph_id)
    if max_paragraph_id is not None:
        stmt = stmt.where(Paragraph.paragraph_id <= max_paragraph_id)

    results: list[KeywordMatchRow] = []
    for row in session.execute(stmt).all():
        paragraph_text = str(row.text or "")
        # 2026-08-13 P2-6：与 SQL 侧一致，Python 侧匹配也做 lower 归一
        matched = tuple(
            keyword for keyword in normalized if keyword in paragraph_text.lower()
        )
        if not matched:
            continue
        results.append(
            KeywordMatchRow(
                paragraph_id=int(row.paragraph_id),
                chunk_id=int(row.chunk_id),
                paragraph_index=int(row.paragraph_index),
                paragraph_text=paragraph_text,
                local_start_char=int(row.local_start_char),
                local_end_char=int(row.local_end_char),
                global_start_char=int(row.global_start_char),
                global_end_char=int(row.global_end_char),
                matched_keywords=matched,
                match_count=len(matched),
            )
        )

    results.sort(key=lambda item: (-item.match_count, item.paragraph_id))
    if top_k <= 0:
        return []
    return results[:top_k]


def fetch_chunk_text(session: Session, run_id: str, chunk_id: int) -> str | None:
    """
    2026-08-02 用于按 run_id 与 chunk_id 读取单个历史 chunk 原文
    不存在对应记录时返回 None
    """
    stmt = select(Chunk.text).where(Chunk.run_id == run_id, Chunk.chunk_id == chunk_id)
    return session.execute(stmt).scalar_one_or_none()

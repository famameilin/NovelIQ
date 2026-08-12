"""
chunk 关键词检索与原文读取

- search_paragraphs_by_keywords: rg 风格关键词子串精确匹配，按命中关键词数排序
- fetch_chunk_text: 读取指定 chunk 的原文全文（read 工具的数据源）
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.chunking.chunker import split_paragraphs
from src.storage.models import Chunk


@dataclass(frozen=True)
class KeywordMatchRow:
    """关键词检索段落 DTO，携带命中的关键词明细与全文定位"""

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
    exclude_chunk_ids: Sequence[int] | None = None,
    min_chunk_id: int | None = None,
    max_chunk_id: int | None = None,
) -> list[KeywordMatchRow]:
    """
    2026-08-03 用于以 chunks.text 为原文真相按关键词字面匹配历史自然段
    返回按命中关键词数与原文顺序稳定排序的段落 DTO
    """
    normalized = list(dict.fromkeys(kw.strip() for kw in keywords if kw and kw.strip()))
    if not normalized:
        return []

    match_expressions = [
        Chunk.text.contains(keyword, autoescape=True)
        for keyword in normalized
    ]
    stmt = (
        select(
            Chunk.chunk_id,
            Chunk.char_offset,
            Chunk.char_end_offset,
            Chunk.text,
        )
        .where(
            Chunk.run_id == run_id,
            or_(*match_expressions),
        )
        .order_by(Chunk.chunk_id.asc())
    )
    if exclude_chunk_ids:
        stmt = stmt.where(Chunk.chunk_id.not_in(list(exclude_chunk_ids)))
    if min_chunk_id is not None:
        stmt = stmt.where(Chunk.chunk_id >= min_chunk_id)
    if max_chunk_id is not None:
        stmt = stmt.where(Chunk.chunk_id <= max_chunk_id)

    matching_rows = session.execute(stmt).all()
    # 旧数据可能缺少 char_offset。此时必须把中间未命中的 chunk 一并计入，
    # 否则后续命中自然段的全局偏移会提前漂移。
    needs_offset_fallback = any(getattr(row, "char_offset", None) is None for row in matching_rows)
    if needs_offset_fallback:
        all_rows_stmt = (
            select(
                Chunk.chunk_id,
                Chunk.char_offset,
                Chunk.char_end_offset,
                Chunk.text,
            )
            .where(Chunk.run_id == run_id)
            .order_by(Chunk.chunk_id.asc())
        )
        if exclude_chunk_ids:
            all_rows_stmt = all_rows_stmt.where(Chunk.chunk_id.not_in(list(exclude_chunk_ids)))
        if min_chunk_id is not None:
            all_rows_stmt = all_rows_stmt.where(Chunk.chunk_id >= min_chunk_id)
        if max_chunk_id is not None:
            all_rows_stmt = all_rows_stmt.where(Chunk.chunk_id <= max_chunk_id)
        rows = session.execute(all_rows_stmt).all()
    else:
        rows = matching_rows
    results: list[KeywordMatchRow] = []
    fallback_global_offset = 0
    for row in rows:
        chunk_id = int(row.chunk_id)
        chunk_text = str(row.text or "")
        raw_chunk_offset = getattr(row, "char_offset", None)
        raw_chunk_end_offset = getattr(row, "char_end_offset", None)
        chunk_offset = (
            int(raw_chunk_offset)
            if raw_chunk_offset is not None
            else fallback_global_offset
        )
        for paragraph_index, (local_start_char, local_end_char, paragraph_text) in enumerate(
            split_paragraphs(chunk_text)
        ):
            matched = tuple(keyword for keyword in normalized if keyword in paragraph_text)
            if not matched:
                continue
            results.append(
                KeywordMatchRow(
                    chunk_id=chunk_id,
                    paragraph_index=paragraph_index,
                    paragraph_text=paragraph_text,
                    local_start_char=local_start_char,
                    local_end_char=local_end_char,
                    global_start_char=chunk_offset + local_start_char,
                    global_end_char=chunk_offset + local_end_char,
                    matched_keywords=matched,
                    match_count=len(matched),
                )
            )
        fallback_global_offset = (
            int(raw_chunk_end_offset)
            if raw_chunk_end_offset is not None
            else max(fallback_global_offset, chunk_offset + len(chunk_text))
        )

    results.sort(key=lambda item: (-item.match_count, item.chunk_id, item.paragraph_index))
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

"chunk 关键词检索与原文读取"

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.storage.models import Chapter, Paragraph
from src.storage.query_terms import like_pattern, term_matches
from src.storage.records.keyword_ops import KeywordMatchRow
from src.storage.repositories.paragraph.reader import join_chapter_body, paragraph_projection


def search_paragraphs_by_keywords(
    session: Session,
    run_id: str,
    keywords: Sequence[str],
    top_k: int = 10,
    exclude_paragraph_ids: Sequence[int] | None = None,
    min_paragraph_id: int | None = None,
    max_paragraph_id: int | None = None,
    before_chapter_sequence: int | None = None,
    after_chapter_sequence: int | None = None,
) -> list[KeywordMatchRow]:
    "二期段落化：直接扫 paragraphs 事实源（不再扫 chunks + Python 重切段），"

    # SQL 与 Python 两侧都以小写对比，避免英文词大小写不一致漏命中
    normalized = list(dict.fromkeys(kw.strip().lower() for kw in keywords if kw and kw.strip()))
    if not normalized:
        return []

    # SQL 侧对原文做 lower() 归一，避免 LIKE 大小写敏感导致英文词漏命中
    match_expressions = [func.lower(Paragraph.text).like(like_pattern(keyword)) for keyword in normalized]
    # 章节连接由 join_chapter_body 统一提供（global 坐标投影基准）；
    # 不再重复声明 Chapter 连接，避免同一查询里 chapters 别名重复
    stmt = join_chapter_body(
        select(*paragraph_projection()).where(
            Paragraph.run_id == run_id,
            or_(*match_expressions),
        )
    )
    if exclude_paragraph_ids:
        stmt = stmt.where(Paragraph.paragraph_id.not_in(list(exclude_paragraph_ids)))
    if min_paragraph_id is not None:
        stmt = stmt.where(Paragraph.paragraph_id >= min_paragraph_id)
    if max_paragraph_id is not None:
        stmt = stmt.where(Paragraph.paragraph_id <= max_paragraph_id)
    if before_chapter_sequence is not None:
        stmt = stmt.where(Chapter.sequence < before_chapter_sequence)
    if after_chapter_sequence is not None:
        stmt = stmt.where(Chapter.sequence > after_chapter_sequence)
    stmt = stmt.order_by(Paragraph.paragraph_id.asc())

    results: list[KeywordMatchRow] = []
    for row in session.execute(stmt).all():
        paragraph_text = str(row.text or "")

        matched = tuple(keyword for keyword in normalized if term_matches(keyword, paragraph_text.lower()))
        if not matched:
            continue
        results.append(
            KeywordMatchRow(
                paragraph_id=int(row.paragraph_id),
                chapter_id=int(row.chapter_id),
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


def fetch_chunk_text(session: Session, run_id: str, chapter_id: int) -> str | None:
    "用于按 run_id 与 chapter_id 读取单个历史章节原文"
    stmt = select(Chapter.text).where(Chapter.run_id == run_id, Chapter.chapter_id == chapter_id)
    return session.execute(stmt).scalar_one_or_none()

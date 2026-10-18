"""
段落事实源读取（paragraphs 事实源）

提供 run 存在性判断、段落行计数与按 paragraph_id keyset 游标的分批读取
（limit=None 返回全部行）。

读取投影（均不落列）：
- local_end_char = local_start_char + 字符长度(text)
- global 坐标 = 所属 chapters.char_offset + 局部边界
- char_count = 字符长度(text)；token_count = paragraph_metrics.token_count
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from src.storage.models import Chapter, Paragraph, ParagraphMetric


def paragraph_projection(*, text_label: str | None = None) -> tuple:
    """返回段落身份/原文与投影坐标列（读取侧唯一口径）

    返回列为 local_end_char/global_start_char/global_end_char/char_count；
    text_label 供语义检索等处指定列别名（如 paragraph_text）。
    """
    char_length = func.char_length(Paragraph.text)
    return (
        Paragraph.paragraph_id,
        Paragraph.chapter_id,
        Paragraph.paragraph_index,
        Paragraph.source_paragraph_index,
        Paragraph.fragment_index,
        Paragraph.local_start_char,
        (Paragraph.local_start_char + char_length).label("local_end_char"),
        (Chapter.char_offset + Paragraph.local_start_char).label("global_start_char"),
        (Chapter.char_offset + Paragraph.local_start_char + char_length).label("global_end_char"),
        char_length.label("char_count"),
        Paragraph.text if text_label is None else Paragraph.text.label(text_label),
    )


def join_chapter_body(statement: Select) -> Select:
    """连接段落所属章节（global 坐标投影基准）

    外连接：章节缺正文时 global 投影为空值，段落行本身不丢。
    """
    return statement.outerjoin(
        Chapter,
        (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id),
    )


def join_paragraph_metrics(statement: Select) -> Select:
    """连接段落指标行（token_count 投影来源）

    外连接：缺指标行时 token_count 为空值。
    """
    return statement.outerjoin(
        ParagraphMetric,
        (ParagraphMetric.run_id == Paragraph.run_id) & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
    )


def has_paragraphs(session: Session, run_id: str) -> bool:
    """run 是否存在段落行"""
    statement = select(Paragraph.paragraph_id).where(Paragraph.run_id == run_id).limit(1)
    return session.execute(statement).scalar_one_or_none() is not None


def count_paragraphs(session: Session, run_id: str) -> int:
    """统计指定 run 的段落行数"""
    statement = select(func.count()).select_from(Paragraph).where(Paragraph.run_id == run_id)
    return int(session.execute(statement).scalar_one() or 0)


def fetch_paragraph_rows_batch(
    session: Session,
    run_id: str,
    *,
    chapter_id: int | None = None,
    after_id: int | None = None,
    limit: int | None = 128,
) -> Sequence[Row]:
    """
    按 paragraph_id keyset 游标分批读取段落行

    after_id 为上一批最后一条 paragraph_id（不含），limit 为每批行数；
    limit=None 时返回全部行（等价 fetch_paragraph_rows）。
    坐标/长度/token_count 由投影得到（见模块说明）。

    Returns:
        sqlalchemy.engine.Row 序列，支持字段名访问
    """
    statement = join_chapter_body(
        join_paragraph_metrics(select(*paragraph_projection(), ParagraphMetric.token_count))
    ).where(Paragraph.run_id == run_id)
    if chapter_id is not None:
        statement = statement.where(Paragraph.chapter_id == chapter_id)
    if after_id is not None:
        statement = statement.where(Paragraph.paragraph_id > after_id)
    statement = statement.order_by(Paragraph.paragraph_id)
    if limit is not None:
        statement = statement.limit(limit)
    return session.execute(statement).all()

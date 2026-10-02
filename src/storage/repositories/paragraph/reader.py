"""
段落事实源读取（paragraphs 事实源，§5.1）

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 paragraph_repository.py 提取段落行读取逻辑
说明: 纯结构搬移，不改查询行为。提供 run 存在性判断、段落行计数与
按 paragraph_id keyset 游标的分批读取（limit=None 返回全部行）。
fetch_paragraph_rows / fetch_chapter_paragraph_rows 为不同默认参数的
便捷入口，保留在 ParagraphRepository 门面上直接委托 fetch_paragraph_rows_batch。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.storage.models import Paragraph


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

    Returns:
        sqlalchemy.engine.Row 序列，支持字段名访问
    """
    statement = (
        select(
            Paragraph.paragraph_id,
            Paragraph.chapter_id,
            Paragraph.paragraph_index,
            Paragraph.source_paragraph_index,
            Paragraph.fragment_index,
            Paragraph.local_start_char,
            Paragraph.local_end_char,
            Paragraph.global_start_char,
            Paragraph.global_end_char,
            Paragraph.char_count,
            Paragraph.token_count,
            Paragraph.text,
        )
        .where(Paragraph.run_id == run_id)
        .order_by(Paragraph.paragraph_id)
    )
    if chapter_id is not None:
        statement = statement.where(Paragraph.chapter_id == chapter_id)
    if after_id is not None:
        statement = statement.where(Paragraph.paragraph_id > after_id)
    if limit is not None:
        statement = statement.limit(limit)
    return session.execute(statement).all()

"""
段落事实源读取（paragraphs 事实源，§5.1）

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 paragraph_repository.py 提取段落行读取逻辑
说明: 纯结构搬移，不改查询行为。提供 run 存在性判断、段落行计数与
按 paragraph_id keyset 游标的分批读取（limit=None 返回全部行）。
fetch_paragraph_rows 为读取全部段落的
便捷入口，保留在 ParagraphRepository 门面上直接委托 fetch_paragraph_rows_batch。

2026-10-16 全库 3NF 改造（35 表冻结结构，读取投影）：
- local_end_char = local_start_char + 字符长度(text)
- global 坐标 = 所属 chapters.char_offset + 局部边界（正文与目录同键一对一）
- char_count = 字符长度(text)（数据库字符单位，不用字节长度）
- token_count = paragraph_metrics.token_count（指标与预处理同批 token 的唯一口径）
上述值都不再落列，投影表达式在本模块统一定义，检索侧共用同一口径。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from src.storage.models import Chapter, Paragraph, ParagraphMetric


def paragraph_projection(*, text_label: str | None = None) -> tuple:
    """2026-10-16 用于返回段落身份/原文与投影坐标列（读取侧唯一口径）

    返回的列名与 3NF 前的段落行一致（local_end_char/global_start_char/
    global_end_char/char_count），下游读取方形状不变；text_label 供语义检索
    等处沿用原列别名（如 paragraph_text）。
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
    """2026-10-16 用于连接段落所属章节（global 坐标投影基准）

    外连接：章节缺正文（空正文章节）时 global 投影为空值，段落行本身不丢；
    正式链中段落所属章节必有正文，空值只表示数据不自洽。
    """
    return statement.outerjoin(
        Chapter,
        (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id),
    )


def join_paragraph_metrics(statement: Select) -> Select:
    """2026-10-16 用于连接段落指标行（token_count 投影来源）

    外连接：缺指标行时 token_count 为空值（观测只能用指标阶段真实值）。
    """
    return statement.outerjoin(
        ParagraphMetric,
        (ParagraphMetric.run_id == Paragraph.run_id)
        & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
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

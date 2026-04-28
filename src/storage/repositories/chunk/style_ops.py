"""
分块风格数据操作

fetch_chunk_styles_full 返回 Row 对象而非元组，支持字段名访问，避免索引错位
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Mapper, Session

from src.storage.models import ChunkStyle
from src.storage.repositories.chunk import ChunkStyleData


def fetch_chunk_styles(session: Session, run_id: str) -> Sequence[Row]:
    """
    获取分块风格数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        Row 对象序列，支持 row.chunk_id / row.dialogue_ratio / row.sent_len_std / row.avg_sent_len

    不再转换成 tuple，下游通过字段名读取风格指标，避免列顺序错位
    """
    stmt = select(
        ChunkStyle.chunk_id,
        ChunkStyle.dialogue_ratio,
        ChunkStyle.sent_len_std,
        ChunkStyle.avg_sent_len,
    ).where(ChunkStyle.run_id == run_id)
    result = session.execute(stmt)
    return result.fetchall()


def insert_chunk_style(session: Session, run_id: str, rows: Iterable[ChunkStyleData] | Iterable[Any]) -> None:
    """
    插入分块风格数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        rows: 风格数据行
    """
    session.execute(delete(ChunkStyle).where(ChunkStyle.run_id == run_id))
    style_rows = []
    for row in rows:
        if isinstance(row, ChunkStyleData):
            style_rows.append(row.to_dict(run_id))
        else:
            style_rows.append(cast(dict, row))
    if style_rows:
        session.bulk_insert_mappings(cast(Mapper[Any], ChunkStyle), style_rows)


def fetch_chunk_styles_full(session: Session, run_id: str) -> Sequence[Row]:
    """
    获取完整的分块风格数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        Row 对象序列，支持通过字段名访问（如 row.d_value, row.pause_density）

    返回 Row 对象而非元组，支持字段名访问，避免索引错位问题
    """
    stmt = (
        select(
            ChunkStyle.chunk_id,
            ChunkStyle.mtld,
            ChunkStyle.ttr,
            ChunkStyle.avg_sent_len,
            ChunkStyle.sent_len_std,
            ChunkStyle.d_value,
            ChunkStyle.pause_density,
            ChunkStyle.fight_density,
            ChunkStyle.exclaim_density,
            ChunkStyle.dialogue_ratio,
            ChunkStyle.question_density,
            ChunkStyle.sensory_density,
            ChunkStyle.metaphor_density,
            ChunkStyle.imagery_lexicon_density,
            ChunkStyle.function_word_vector,
        )
        .where(ChunkStyle.run_id == run_id)
        .order_by(ChunkStyle.chunk_id)
    )
    result = session.execute(stmt)
    return result.fetchall()


def fetch_chunk_imagery_lexicon_densities(session: Session, run_id: str) -> list[tuple[int, float | None]]:
    """
    获取每个 chunk 的 imagery_lexicon_density

    直接从 chunk_style 读取 imagery 字段，替代历史 culture 兼容接口
    """
    stmt = (
        select(
            ChunkStyle.chunk_id,
            ChunkStyle.imagery_lexicon_density,
        )
        .where(ChunkStyle.run_id == run_id)
        .order_by(ChunkStyle.chunk_id)
    )
    result = session.execute(stmt)
    return [(row.chunk_id, row.imagery_lexicon_density) for row in result.fetchall()]

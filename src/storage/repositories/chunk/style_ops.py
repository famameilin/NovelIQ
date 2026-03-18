"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分chunk_repository.py
说明: 分块风格数据操作
"""

from __future__ import annotations

from typing import Any, Iterable, List, Tuple, Union, cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.storage.models import ChunkStyle
from src.storage.repositories.chunk import ChunkStyleData


def fetch_chunk_styles(
    session: Session, run_id: str
) -> List[Tuple[int, float, float, float]]:
    """
    获取分块风格数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        (chunk_id, dialogue_ratio, sent_len_std, avg_sent_len) 元组列表
    """
    stmt = select(
        ChunkStyle.chunk_id,
        ChunkStyle.dialogue_ratio,
        ChunkStyle.sent_len_std,
        ChunkStyle.avg_sent_len,
    ).where(ChunkStyle.run_id == run_id)
    result = session.execute(stmt)
    return [(row[0], row[1], row[2], row[3]) for row in result.fetchall()]


def insert_chunk_style(
    session: Session, run_id: str, rows: Union[Iterable[ChunkStyleData], Iterable[Any]]
) -> None:
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
        session.bulk_insert_mappings(ChunkStyle, style_rows)


def fetch_chunk_styles_full(
    session: Session, run_id: str
) -> List[
    Tuple[
        int,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        str,
    ]
]:
    """
    获取完整的分块风格数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        (chunk_id, mtld, ttr, avg_sent_len, sent_len_std, d_value, pause_density, fight_density, exclaim_density, dialogue_ratio, question_density, sensory_density, metaphor_density, cultural_density, function_word_vector) 元组列表
    """
    stmt = select(
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
        ChunkStyle.cultural_density,
        ChunkStyle.function_word_vector,
    ).where(ChunkStyle.run_id == run_id)
    result = session.execute(stmt)
    return [tuple(row) for row in result.fetchall()]

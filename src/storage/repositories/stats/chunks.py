"""
分块统计相关操作

情绪曲线、节奏曲线、文化数据等分块相关操作

合并 EmotionCurve + RhythmCurve 为 ChunkCurve
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row

from src.storage.models import ChunkCurve, ChunkStyle

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_chunk_curve(
    session: Session,
    run_id: str,
    rows: Iterable[tuple[int, float, float, float, float, float, float]],
) -> None:
    """
    插入分块曲线数据（情绪 + 节奏）

    Args:
        session: 数据库会话
        run_id: 运行ID
        rows: 曲线数据迭代器
            (chunk_id, pos_density, neg_density, net_density, smoothed_density,
             tension_proxy, tension_composite)
    """
    data_list = list(rows)
    if not data_list:
        return

    for (
        chunk_id,
        pos_density,
        neg_density,
        net_density,
        smoothed_density,
        tension_proxy,
        tension_composite,
    ) in data_list:
        stmt = (
            pg_insert(ChunkCurve)
            .values(
                chunk_id=chunk_id,
                pos_density=pos_density,
                neg_density=neg_density,
                net_density=net_density,
                smoothed_density=smoothed_density,
                tension_proxy=tension_proxy,
                tension_composite=tension_composite,
                run_id=run_id,
            )
            .on_conflict_do_update(
                index_elements=["chunk_id", "run_id"],
                set_={
                    "pos_density": pos_density,
                    "neg_density": neg_density,
                    "net_density": net_density,
                    "smoothed_density": smoothed_density,
                    "tension_proxy": tension_proxy,
                    "tension_composite": tension_composite,
                },
            )
        )
        session.execute(stmt)
    session.commit()


def fetch_chunk_culture(session: Session, run_id: str) -> Sequence[Row]:
    """
    获取分块文化数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        Row 对象序列，支持 row.imagery_lexicon_density 字段名访问

    删除低价值词表密度字段，只返回 imagery_lexicon_density
    """
    stmt = (
        select(
            ChunkStyle.imagery_lexicon_density,
        )
        .where(ChunkStyle.run_id == run_id)
        .order_by(ChunkStyle.chunk_id)
    )

    return session.execute(stmt).fetchall()


def fetch_chunk_curves_full(session: Session, run_id: str) -> Sequence[Row]:
    """
    获取分块曲线完整数据（情绪 + 节奏）

    返回 Sequence[Row] 支持字段名访问，替代元组列表

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        Row 对象序列，支持字段名访问：
        row.chunk_id, row.pos_density, row.neg_density, row.net_density,
        row.smoothed_density, row.tension_proxy, row.tension_composite
    """
    stmt = (
        select(
            ChunkCurve.chunk_id,
            ChunkCurve.pos_density,
            ChunkCurve.neg_density,
            ChunkCurve.net_density,
            ChunkCurve.smoothed_density,
            ChunkCurve.tension_proxy,
            ChunkCurve.tension_composite,
        )
        .where(ChunkCurve.run_id == run_id)
        .order_by(ChunkCurve.chunk_id)
    )

    result = session.execute(stmt)
    return result.fetchall()


def fetch_emotion_densities(session: Session, run_id: str) -> Sequence[Row]:
    """
    获取情绪密度数据

    返回 Sequence[Row] 支持字段名访问，替代元组列表

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        Row 对象序列，支持字段名访问： row.pos_density, row.neg_density
    """
    stmt = (
        select(
            ChunkCurve.pos_density,
            ChunkCurve.neg_density,
        )
        .where(ChunkCurve.run_id == run_id)
        .order_by(ChunkCurve.chunk_id)
    )

    result = session.execute(stmt)
    return result.fetchall()

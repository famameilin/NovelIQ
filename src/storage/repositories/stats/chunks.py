"""
分块统计相关操作

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 拆分stats_repository
说明: 情绪曲线、节奏曲线、文化数据等分块相关操作
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, List, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models import EmotionCurve, RhythmCurve, ChunkCulture

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_emotion_curve(session: Session, run_id: str, rows: Iterable[Tuple[int, float, float, float, float]]) -> None:
    """
    插入情绪曲线数据

    Args:
        session: 数据库会话
        run_id: 运行ID
        rows: 情绪数据迭代器 (chunk_id, pos_density, neg_density, net_density, smoothed_density)
    """
    data_list = list(rows)
    if not data_list:
        return

    for chunk_id, pos_density, neg_density, net_density, smoothed_density in data_list:
        stmt = (
            pg_insert(EmotionCurve)
            .values(
                chunk_id=chunk_id,
                pos_density=pos_density,
                neg_density=neg_density,
                net_density=net_density,
                smoothed_density=smoothed_density,
                run_id=run_id,
            )
            .on_conflict_do_update(
                index_elements=["chunk_id", "run_id"],
                set_={
                    "pos_density": pos_density,
                    "neg_density": neg_density,
                    "net_density": net_density,
                    "smoothed_density": smoothed_density,
                },
            )
        )
        session.execute(stmt)
    session.commit()


def insert_rhythm_curve(session: Session, run_id: str, rows: Iterable[Tuple[int, float, float]]) -> None:
    """
    插入节奏曲线数据

    Args:
        session: 数据库会话
        run_id: 运行ID
        rows: 节奏数据迭代器 (chunk_id, tension_proxy, tension_composite)
    """
    data_list = list(rows)
    if not data_list:
        return

    for chunk_id, tension_proxy, tension_composite in data_list:
        stmt = (
            pg_insert(RhythmCurve)
            .values(
                chunk_id=chunk_id,
                tension_proxy=tension_proxy,
                tension_composite=tension_composite,
                run_id=run_id,
            )
            .on_conflict_do_update(
                index_elements=["chunk_id", "run_id"],
                set_={
                    "tension_proxy": tension_proxy,
                    "tension_composite": tension_composite,
                },
            )
        )
        session.execute(stmt)
    session.commit()


def fetch_emotion_curve(session: Session, run_id: str) -> List[Tuple[float, float, float]]:
    """
    获取情绪曲线数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        (pos_density, neg_density, net_density) 元组列表
    """
    stmt = (
        select(
            EmotionCurve.pos_density,
            EmotionCurve.neg_density,
            EmotionCurve.net_density,
        )
        .where(EmotionCurve.run_id == run_id)
        .order_by(EmotionCurve.chunk_id)
    )

    result = session.execute(stmt).fetchall()
    return [(row.pos_density, row.neg_density, row.net_density) for row in result]


def fetch_rhythm_curve(session: Session, run_id: str) -> List[Tuple[float]]:
    """
    获取节奏曲线数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        (tension_composite,) 元组列表
    """
    stmt = select(RhythmCurve.tension_composite).where(RhythmCurve.run_id == run_id).order_by(RhythmCurve.chunk_id)

    result = session.execute(stmt).fetchall()
    return [(row.tension_composite,) for row in result]


def fetch_chunk_culture(session: Session, run_id: str) -> List[Tuple[float | None]]:
    """
    获取分块文化数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        (imagery_density,) 元组列表

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 简化文化指标系统
    修改内容: 删除低价值词表密度字段，只返回 imagery_density
    """
    stmt = (
        select(
            ChunkCulture.imagery_density,
        )
        .where(ChunkCulture.run_id == run_id)
        .order_by(ChunkCulture.chunk_id)
    )

    result = session.execute(stmt).fetchall()
    return [(row.imagery_density,) for row in result]


def fetch_emotion_curve_full(session: Session, run_id: str) -> List[Tuple[int, float, float, float, float]]:
    """
    获取情绪曲线完整数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        (chunk_id, pos_density, neg_density, net_density, smoothed_density) 元组列表
    """
    stmt = (
        select(
            EmotionCurve.chunk_id,
            EmotionCurve.pos_density,
            EmotionCurve.neg_density,
            EmotionCurve.net_density,
            EmotionCurve.smoothed_density,
        )
        .where(EmotionCurve.run_id == run_id)
        .order_by(EmotionCurve.chunk_id)
    )

    result = session.execute(stmt).fetchall()
    return [
        (
            row.chunk_id,
            row.pos_density,
            row.neg_density,
            row.net_density,
            row.smoothed_density,
        )
        for row in result
    ]


def fetch_rhythm_curve_full(session: Session, run_id: str) -> List[Tuple[int, float, float]]:
    """
    获取节奏曲线完整数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        (chunk_id, tension_proxy, tension_composite) 元组列表
    """
    stmt = (
        select(
            RhythmCurve.chunk_id,
            RhythmCurve.tension_proxy,
            RhythmCurve.tension_composite,
        )
        .where(RhythmCurve.run_id == run_id)
        .order_by(RhythmCurve.chunk_id)
    )

    result = session.execute(stmt).fetchall()
    return [
        (
            row.chunk_id,
            row.tension_proxy,
            row.tension_composite,
        )
        for row in result
    ]


def fetch_emotion_densities(session: Session, run_id: str) -> List[Tuple[float, float]]:
    """
    获取情绪密度数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        (pos_density, neg_density) 元组列表
    """
    stmt = (
        select(
            EmotionCurve.pos_density,
            EmotionCurve.neg_density,
        )
        .where(EmotionCurve.run_id == run_id)
        .order_by(EmotionCurve.chunk_id)
    )

    result = session.execute(stmt).fetchall()
    return [(row.pos_density, row.neg_density) for row in result]

"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分chunk_repository.py
说明: 分块主题数据操作
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, func, select
from typing import Any, cast

from sqlalchemy.orm import Mapper, Session

from src.storage.models import ChunkTopic


def insert_chunk_topics(
    session: Session, run_id: str, rows: Iterable[tuple[int, int, float]]
) -> None:
    """
    插入分块主题数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        rows: 主题数据行 (chunk_id, topic_id, topic_weight)
    """
    topic_rows = [
        {
            "chunk_id": row[0],
            "topic_id": row[1],
            "topic_weight": row[2],
            "run_id": run_id,
        }
        for row in rows
    ]
    if topic_rows:
        session.bulk_insert_mappings(cast(Mapper[Any], ChunkTopic), topic_rows)


def clear_chunk_topics(session: Session, run_id: str) -> None:
    """清空分块主题数据"""
    session.execute(delete(ChunkTopic).where(ChunkTopic.run_id == run_id))


def fetch_chunk_topics_agg(session: Session, run_id: str) -> list[tuple[int, float]]:
    """
    获取聚合后的分块主题数据（每个分块的平均主题权重）

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        (chunk_id, avg_topic_weight) 元组列表
    """
    stmt = (
        select(ChunkTopic.chunk_id, func.avg(ChunkTopic.topic_weight).label("avg_weight"))
        .where(ChunkTopic.run_id == run_id)
        .group_by(ChunkTopic.chunk_id)
    )
    result = session.execute(stmt)
    return [(row[0], row[1]) for row in result.fetchall()]

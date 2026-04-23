"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分chunk_repository.py
说明: 分块主题数据操作
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Mapper, Session

from src.storage.models import ChunkTopic


def insert_chunk_topics(session: Session, run_id: str, rows: Iterable[tuple[int, int, float]]) -> None:
    """
    插入分块主题数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        rows: 主题数据行 (chunk_id, topic_id, topic_weight)
    """
    topic_rows = [
        {
            "chunk_id": chunk_id,
            "topic_id": topic_id,
            "topic_weight": topic_weight,
            "run_id": run_id,
        }
        for chunk_id, topic_id, topic_weight in rows
    ]
    if topic_rows:
        session.bulk_insert_mappings(cast(Mapper[Any], ChunkTopic), topic_rows)


def clear_chunk_topics(session: Session, run_id: str) -> None:
    """清空分块主题数据"""
    session.execute(delete(ChunkTopic).where(ChunkTopic.run_id == run_id))


def fetch_chunk_topics_agg(session: Session, run_id: str) -> Sequence[Row]:
    """
    获取聚合后的主题数据（每个主题的全局总权重）

    使用 SUM 而非 AVG，使热门主题（高出现频率 × 高概率）获得更高权重，
    归一化后能体现各主题在全书中的相对重要程度差异。

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        Row 对象序列，支持字段名访问：row.topic_id, row.total_weight
    """
    stmt = (
        select(ChunkTopic.topic_id, func.sum(ChunkTopic.topic_weight).label("total_weight"))
        .where(ChunkTopic.run_id == run_id)
        .group_by(ChunkTopic.topic_id)
    )
    result = session.execute(stmt)
    return result.fetchall()

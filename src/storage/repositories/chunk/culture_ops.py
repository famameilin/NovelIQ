"""
分块文化数据操作（合并到 ChunkStyle 表）

imagery_lexicon_density 字段已从 chunk_culture 表迁移到 chunk_style 表。
本模块提供兼容性接口，将数据读写委托给 style_ops。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import ChunkStyle


def insert_chunk_culture(
    session: Session,
    run_id: str,
    rows: Iterable[tuple[int, float | None]],
) -> None:
    """
    插入分块文化数据（写入 chunk_style.imagery_lexicon_density）

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        rows: 文化数据行 (chunk_id, imagery_lexicon_density)
    """
    for chunk_id, density in rows:
        stmt = select(ChunkStyle).where(
            ChunkStyle.chunk_id == chunk_id,
            ChunkStyle.run_id == run_id,
        )
        style = session.execute(stmt).scalar_one_or_none()
        if style is not None:
            style.imagery_lexicon_density = density


def fetch_chunk_cultures_full(session: Session, run_id: str) -> list[tuple[int, float | None]]:
    """
    获取完整的分块文化数据（从 chunk_style 读取）

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        (chunk_id, imagery_lexicon_density) 元组列表
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

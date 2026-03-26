"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分chunk_repository.py
说明: 分块文化数据操作

修改时间: 2026-03-26
修改者: TraeAI
任务: 简化文化指标系统
修改内容: 删除低价值词表密度字段，只保留 imagery_lexicon_density
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.storage.models import ChunkCulture


def insert_chunk_culture(
    session: Session,
    run_id: str,
    rows: Iterable[tuple[int, float | None]],
) -> None:
    """
    插入分块文化数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        rows: 文化数据行 (chunk_id, imagery_lexicon_density)
    """
    session.execute(delete(ChunkCulture).where(ChunkCulture.run_id == run_id))
    culture_rows = [
        {
            "chunk_id": row[0],
            "imagery_lexicon_density": row[1],
            "run_id": run_id,
        }
        for row in rows
    ]
    if culture_rows:
        session.bulk_insert_mappings(ChunkCulture, culture_rows)  # type: ignore[arg-type]


def fetch_chunk_cultures_full(session: Session, run_id: str) -> list[tuple[int, float | None]]:
    """
    获取完整的分块文化数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        (chunk_id, imagery_lexicon_density) 元组列表
    """
    stmt = select(
        ChunkCulture.chunk_id,
        ChunkCulture.imagery_lexicon_density,
    ).where(ChunkCulture.run_id == run_id).order_by(ChunkCulture.chunk_id)
    result = session.execute(stmt)
    return [tuple(row) for row in result.fetchall()]

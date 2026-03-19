"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分chunk_repository.py
说明: 分块文化数据操作
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.storage.models import ChunkCulture


def insert_chunk_culture(
    session: Session,
    run_id: str,
    rows: Iterable[Tuple[int, float, float, float, float, float, float]],
) -> None:
    """
    插入分块文化数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        rows: 文化数据行 (chunk_id, confucian_density, taoist_density, buddhist_density, folk_density, allusion_density, imagery_density)
    """
    session.execute(delete(ChunkCulture).where(ChunkCulture.run_id == run_id))
    culture_rows = [
        {
            "chunk_id": row[0],
            "confucian_density": row[1],
            "taoist_density": row[2],
            "buddhist_density": row[3],
            "folk_density": row[4],
            "allusion_density": row[5],
            "imagery_density": row[6],
            "run_id": run_id,
        }
        for row in rows
    ]
    if culture_rows:
        session.bulk_insert_mappings(ChunkCulture, culture_rows)  # type: ignore[arg-type]


def fetch_chunk_cultures_full(
    session: Session, run_id: str
) -> List[Tuple[int, float, float, float, float, float]]:
    """
    获取完整的分块文化数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        (chunk_id, confucian_density, taoist_density, buddhist_density, folk_density, allusion_density) 元组列表
    """
    stmt = select(
        ChunkCulture.chunk_id,
        ChunkCulture.confucian_density,
        ChunkCulture.taoist_density,
        ChunkCulture.buddhist_density,
        ChunkCulture.folk_density,
        ChunkCulture.allusion_density,
    ).where(ChunkCulture.run_id == run_id)
    result = session.execute(stmt)
    return [tuple(row) for row in result.fetchall()]

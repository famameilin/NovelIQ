"""
地点数据存储操作

创建时间: 2026-03-28
创建者: TraeAI
任务: implement-location-entity-type
说明: 地点信息的存储和查询操作
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import ChunkLocation

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def save_chunk_locations(
    session: "Session",
    chunk_id: int,
    locations: list[dict],
    run_id: str,
    novel_id: str,
) -> int:
    """
    保存 chunk 的地点信息

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: implement-location-entity-type
    说明: 将 Phase1 识别的地点存储到 chunk_locations 表

    Args:
        session: SQLAlchemy Session
        chunk_id: chunk ID
        locations: 地点列表，格式 [{"raw_name": "产房", "location_type": "room"}, ...]
        run_id: 运行 ID
        novel_id: 小说 ID

    Returns:
        插入的记录数
    """
    if not locations:
        return 0

    records = []
    for loc in locations:
        raw_name = loc.get("raw_name", "")
        if not raw_name:
            continue
        records.append({
            "chunk_id": chunk_id,
            "location_name": raw_name,
            "location_type": loc.get("location_type"),
            "run_id": run_id,
            "novel_id": novel_id,
        })

    if not records:
        return 0

    stmt = insert(ChunkLocation.__table__).values(records)
    stmt = stmt.on_conflict_do_nothing()
    result = session.execute(stmt)
    session.flush()

    count = len(records)
    logger.debug(f"Saved {count} locations for chunk {chunk_id}")
    return count


def fetch_chunk_locations(
    session: "Session",
    chunk_id: int,
    run_id: str,
) -> list[dict]:
    """
    获取 chunk 的地点信息

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: implement-location-entity-type
    说明: 从 chunk_locations 表获取指定 chunk 的地点列表

    Args:
        session: SQLAlchemy Session
        chunk_id: chunk ID
        run_id: 运行 ID

    Returns:
        [{"location_name": "产房", "location_type": "room"}, ...]
    """
    stmt = select(ChunkLocation.location_name, ChunkLocation.location_type).where(
        ChunkLocation.chunk_id == chunk_id,
        ChunkLocation.run_id == run_id,
    )
    result = session.execute(stmt).fetchall()

    return [{"location_name": row[0], "location_type": row[1]} for row in result]


def fetch_all_locations(
    session: "Session",
    run_id: str,
) -> dict[str, int]:
    """
    获取所有地点及其出现频次

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: implement-location-entity-type
    说明: 统计所有地点的出现次数

    Args:
        session: SQLAlchemy Session
        run_id: 运行 ID

    Returns:
        {"产房": 5, "厅堂": 3, ...}
    """
    from sqlalchemy import func

    stmt = (
        select(ChunkLocation.location_name, func.count().label("count"))
        .where(ChunkLocation.run_id == run_id)
        .group_by(ChunkLocation.location_name)
        .order_by(func.count().desc())
    )
    result = session.execute(stmt).fetchall()

    return {row[0]: row[1] for row in result}

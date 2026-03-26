"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 operations.py 拆分关系相关操作

本模块包含实体关系相关的数据库操作函数。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional


def insert_entity_relation(
    conn: sqlite3.Connection,
    novel_id: str,
    from_entity: int,
    to_entity: int,
    rel_type: str,
    first_chunk: Optional[int] = None,
    tension: float = 0.0,
) -> int | None:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO entity_relations (novel_id, from_entity, to_entity, rel_type, first_chunk, last_chunk, tension)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (novel_id, from_entity, to_entity, rel_type, first_chunk, first_chunk, tension),
    )
    conn.commit()
    return cursor.lastrowid


def _fetch_relations(
    conn: sqlite3.Connection,
    novel_id: Optional[str] = None,
    entity_id: Optional[int] = None,
    is_active_only: bool = False,
) -> List[Dict]:
    """
    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-core-data-layer-functions

    辅助函数：统一查询实体关系的 SQL 逻辑。
    """
    base_sql = """
        SELECT rel_id, novel_id, from_entity, to_entity, rel_type, first_chunk, last_chunk, tension, is_active
        FROM entity_relations
    """
    conditions = []
    params: List[Any] = []

    if novel_id is not None:
        conditions.append("novel_id = ?")
        params.append(novel_id)

    if entity_id is not None:
        conditions.append("(from_entity = ? OR to_entity = ?)")
        params.extend([entity_id, entity_id])

    if is_active_only:
        conditions.append("is_active = 1")

    if conditions:
        base_sql += " WHERE " + " AND ".join(conditions)

    base_sql += " ORDER BY last_chunk DESC"

    cursor = conn.execute(base_sql, params)
    rows = cursor.fetchall()
    return [
        {
            "rel_id": row[0],
            "novel_id": row[1],
            "from_entity": row[2],
            "to_entity": row[3],
            "rel_type": row[4],
            "first_chunk": row[5],
            "last_chunk": row[6],
            "tension": row[7],
            "is_active": bool(row[8]),
        }
        for row in rows
    ]


def fetch_relations_for_entity(
    conn: sqlite3.Connection,
    entity_id: int,
    novel_id: Optional[str] = None,
) -> List[Dict]:
    """
    修改时间: 2026-03-13
    修改者: TraeAI
    任务: refactor-core-data-layer-functions
    修改原因: 重构为调用 _fetch_relations 辅助函数，消除重复代码
    """
    return _fetch_relations(
        conn=conn,
        novel_id=novel_id,
        entity_id=entity_id,
        is_active_only=False,
    )


def fetch_active_relations(
    conn: sqlite3.Connection,
    novel_id: str,
    entity_id: Optional[int] = None,
) -> List[Dict]:
    """
    修改时间: 2026-03-13
    修改者: TraeAI
    任务: refactor-core-data-layer-functions
    修改原因: 重构为调用 _fetch_relations 辅助函数，消除重复代码
    """
    return _fetch_relations(
        conn=conn,
        novel_id=novel_id,
        entity_id=entity_id,
        is_active_only=True,
    )


def update_relation_last_chunk(
    conn: sqlite3.Connection,
    rel_id: int,
    last_chunk: int,
) -> None:
    conn.execute(
        "UPDATE entity_relations SET last_chunk = ? WHERE rel_id = ?",
        (last_chunk, rel_id),
    )
    conn.commit()

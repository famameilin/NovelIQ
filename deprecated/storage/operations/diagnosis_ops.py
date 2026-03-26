"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 operations.py 拆分诊断相关操作

本模块包含诊断分析相关的数据库操作函数。
"""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Tuple

from src.config import settings


def fetch_pivot_blocks(conn: sqlite3.Connection, limit: int | None = None) -> List[Tuple[int, str, str]]:
    if limit is None:
        limit = settings.diagnosis.pivot_blocks_limit
    cursor = conn.execute(
        """
        SELECT c.chunk_id, c.text, a.event_type
        FROM chunks c
        JOIN chunk_annotation a ON c.chunk_id = a.chunk_id
        WHERE a.pivot_moment = 1
        ORDER BY c.chunk_id
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()


def fetch_high_tension_chunks(conn: sqlite3.Connection, limit: int | None = None) -> List[Tuple[int, str, float]]:
    if limit is None:
        limit = settings.diagnosis.high_tension_limit
    cursor = conn.execute(
        """
        SELECT c.chunk_id, c.text, ABS(e.net_density) as tension
        FROM chunks c
        JOIN emotion_curve e ON c.chunk_id = e.chunk_id
        WHERE ABS(e.net_density) > 0.01
        ORDER BY tension DESC
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()


def fetch_relation_changes(conn: sqlite3.Connection, limit: int | None = None) -> List[Tuple[int, str, str, str, str]]:
    if limit is None:
        limit = settings.diagnosis.relation_changes_limit
    cursor = conn.execute(
        """
        SELECT chunk_id, from_char, to_char, type, change
        FROM chunk_relations
        ORDER BY chunk_id
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()


def fetch_foreshadowing_chunks(conn: sqlite3.Connection, limit: int | None = None) -> List[Tuple[int, str, str, str]]:
    if limit is None:
        limit = settings.diagnosis.foreshadowing_limit
    cursor = conn.execute(
        """
        SELECT c.chunk_id, c.text, a.foreshadowing_type, a.foreshadowing_desc
        FROM chunks c
        JOIN chunk_annotation a ON c.chunk_id = a.chunk_id
        WHERE a.has_foreshadowing = 1
        ORDER BY c.chunk_id
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()


def fetch_first_last_chunk_summary(conn: sqlite3.Connection, max_chars: int | None = None) -> Tuple[str, str]:
    if max_chars is None:
        max_chars = settings.diagnosis.first_last_max_chars
    cursor = conn.execute("SELECT chunk_id, text FROM chunks ORDER BY chunk_id")
    chunks = cursor.fetchall()
    if not chunks:
        return "", ""
    first_text = chunks[0][1][:max_chars] if chunks[0][1] else ""
    last_text = chunks[-1][1][:max_chars] if chunks[-1][1] else ""
    return first_text, last_text


def fetch_pivot_moments(conn: sqlite3.Connection, limit: int | None = None) -> List[Tuple[int, str]]:
    if limit is None:
        limit = settings.diagnosis.pivot_moments_limit
    cursor = conn.execute(
        """
        SELECT c.chunk_id, c.text
        FROM chunks c
        JOIN chunk_annotation a ON c.chunk_id = a.chunk_id
        WHERE a.event_type = '高潮'
        ORDER BY c.chunk_id
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()


def insert_entity_snapshot(
    conn: sqlite3.Connection,
    novel_id: str,
    entity_id: int,
    chunk_id: int,
    state_json: str,
) -> int | None:
    cursor = conn.execute(
        """
        INSERT OR REPLACE INTO entity_snapshots (novel_id, entity_id, chunk_id, state_json)
        VALUES (?, ?, ?, ?)
        """,
        (novel_id, entity_id, chunk_id, state_json),
    )
    conn.commit()
    return cursor.lastrowid


def fetch_snapshots_by_chunk(
    conn: sqlite3.Connection,
    novel_id: str,
    start_chunk: int,
    end_chunk: int,
) -> List[Dict]:
    cursor = conn.execute(
        """
        SELECT snap_id, novel_id, entity_id, chunk_id, state_json
        FROM entity_snapshots
        WHERE novel_id = ? AND chunk_id >= ? AND chunk_id <= ?
        ORDER BY chunk_id DESC
        """,
        (novel_id, start_chunk, end_chunk),
    )
    rows = cursor.fetchall()
    return [
        {
            "snap_id": row[0],
            "novel_id": row[1],
            "entity_id": row[2],
            "chunk_id": row[3],
            "state_json": row[4],
        }
        for row in rows
    ]


def fetch_recent_snapshots(
    conn: sqlite3.Connection,
    novel_id: str,
    limit: int = 10,
) -> List[Dict]:
    cursor = conn.execute(
        """
        SELECT snap_id, novel_id, entity_id, chunk_id, state_json
        FROM entity_snapshots
        WHERE novel_id = ?
        ORDER BY chunk_id DESC
        LIMIT ?
        """,
        (novel_id, limit),
    )
    rows = cursor.fetchall()
    return [
        {
            "snap_id": row[0],
            "novel_id": row[1],
            "entity_id": row[2],
            "chunk_id": row[3],
            "state_json": row[4],
        }
        for row in rows
    ]

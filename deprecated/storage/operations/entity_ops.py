"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 operations.py 拆分实体相关操作

本模块包含实体相关的数据库操作函数。
"""

from __future__ import annotations

import pickle
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def insert_entity(
    conn: sqlite3.Connection,
    novel_id: str,
    canonical: str,
    entity_type: str,
    first_chunk: Optional[int] = None,
    description: Optional[str] = None,
    confidence: float = 1.0,
) -> int | None:
    cursor = conn.execute(
        """
        INSERT INTO entities (novel_id, canonical, entity_type, first_chunk, last_chunk, description, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (novel_id, canonical, entity_type, first_chunk, first_chunk, description, confidence),
    )
    conn.commit()
    return cursor.lastrowid


def insert_entity_alias(
    conn: sqlite3.Connection,
    entity_id: int,
    alias: str,
    alias_type: Optional[str] = None,
    source_chunk: Optional[int] = None,
) -> int | None:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO entity_aliases (entity_id, alias, alias_type, source_chunk, confirm_count)
        VALUES (?, ?, ?, ?, 1)
        """,
        (entity_id, alias, alias_type, source_chunk),
    )
    conn.commit()
    return cursor.lastrowid


def insert_entity_embedding(
    conn: sqlite3.Connection,
    entity_id: int,
    embedding: List[float],
) -> None:
    blob = pickle.dumps(embedding)
    conn.execute(
        "UPDATE entities SET embedding = ? WHERE entity_id = ?",
        (blob, entity_id),
    )
    conn.commit()


def fetch_entity_by_canonical(
    conn: sqlite3.Connection,
    novel_id: str,
    canonical: str,
) -> Optional[Dict]:
    cursor = conn.execute(
        """
        SELECT entity_id, novel_id, canonical, entity_type, first_chunk, last_chunk, description, embedding, confidence
        FROM entities WHERE novel_id = ? AND canonical = ?
        """,
        (novel_id, canonical),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "entity_id": row[0],
        "novel_id": row[1],
        "canonical": row[2],
        "entity_type": row[3],
        "first_chunk": row[4],
        "last_chunk": row[5],
        "description": row[6],
        "embedding": pickle.loads(row[7]) if row[7] else None,
        "confidence": row[8],
    }


def fetch_entity_by_alias(
    conn: sqlite3.Connection,
    novel_id: str,
    alias: str,
) -> Optional[Dict]:
    cursor = conn.execute(
        """
        SELECT e.entity_id, e.novel_id, e.canonical, e.entity_type, e.first_chunk, e.last_chunk,
               e.description, e.confidence, ea.alias_type, ea.confirm_count
        FROM entities e
        JOIN entity_aliases ea ON e.entity_id = ea.entity_id
        WHERE e.novel_id = ? AND ea.alias = ?
        ORDER BY ea.confirm_count DESC
        LIMIT 1
        """,
        (novel_id, alias),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "entity_id": row[0],
        "novel_id": row[1],
        "canonical": row[2],
        "entity_type": row[3],
        "first_chunk": row[4],
        "last_chunk": row[5],
        "description": row[6],
        "confidence": row[7],
        "alias_type": row[8],
        "confirm_count": row[9],
    }


def fetch_all_aliases_for_entity(
    conn: sqlite3.Connection,
    entity_id: int,
) -> List[Dict]:
    cursor = conn.execute(
        """
        SELECT alias_id, alias, alias_type, source_chunk, confirm_count
        FROM entity_aliases WHERE entity_id = ?
        ORDER BY confirm_count DESC
        """,
        (entity_id,),
    )
    rows = cursor.fetchall()
    return [
        {
            "alias_id": row[0],
            "alias": row[1],
            "alias_type": row[2],
            "source_chunk": row[3],
            "confirm_count": row[4],
        }
        for row in rows
    ]


def update_entity_last_chunk(
    conn: sqlite3.Connection,
    entity_id: int,
    last_chunk: int,
) -> None:
    conn.execute(
        "UPDATE entities SET last_chunk = ? WHERE entity_id = ?",
        (last_chunk, entity_id),
    )
    conn.commit()


def increment_alias_confirm(
    conn: sqlite3.Connection,
    entity_id: int,
    alias: str,
) -> None:
    conn.execute(
        """
        UPDATE entity_aliases SET confirm_count = confirm_count + 1
        WHERE entity_id = ? AND alias = ?
        """,
        (entity_id, alias),
    )
    conn.commit()


def insert_entity_registry(
    conn: sqlite3.Connection,
    chunk_id: int,
    name: str,
    role: str,
    last_action: str,
    last_emotion: str,
    emotion_score: int,
) -> None:
    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT INTO entity_registry (chunk_id, name, role, last_action, last_emotion, emotion_score, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (chunk_id, name, role, last_action, last_emotion, emotion_score, now),
    )
    conn.commit()


def fetch_active_entities(
    conn: sqlite3.Connection,
    current_chunk_id: int,
    lookback: int = 10,
) -> List[Tuple[int, str, str, str, str, int]]:
    start_chunk = max(0, current_chunk_id - lookback)
    cursor = conn.execute(
        """
        SELECT entity_id, name, role, last_action, last_emotion, emotion_score
        FROM entity_registry
        WHERE chunk_id >= ? AND chunk_id <= ?
        ORDER BY chunk_id DESC, entity_id DESC
        """,
        (start_chunk, current_chunk_id),
    )
    return cursor.fetchall()

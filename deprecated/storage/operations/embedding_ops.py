"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 operations.py 拆分嵌入相关操作

本模块包含嵌入向量相关的数据库操作函数。
"""

from __future__ import annotations

import pickle
import sqlite3
from datetime import datetime
from typing import List, Optional


def insert_chunk_embedding(
    conn: sqlite3.Connection,
    chunk_id: int,
    embedding: List[float],
) -> None:
    now = datetime.now().isoformat()
    blob = pickle.dumps(embedding)
    conn.execute(
        """
        INSERT OR REPLACE INTO chunk_embeddings (chunk_id, embedding, created_at)
        VALUES (?, ?, ?)
        """,
        (chunk_id, blob, now),
    )
    conn.commit()


def fetch_chunk_embedding(
    conn: sqlite3.Connection,
    chunk_id: int,
) -> Optional[List[float]]:
    cursor = conn.execute(
        "SELECT embedding FROM chunk_embeddings WHERE chunk_id = ?",
        (chunk_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return pickle.loads(row[0])


def get_embedding_dim(embedding_client) -> int:
    test_vec = embedding_client.get_embedding("测试")
    return len(test_vec)

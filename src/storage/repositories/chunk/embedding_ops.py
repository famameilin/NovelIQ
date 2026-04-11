"""
创建时间: 2026-04-10
创建者: TraeAI
任务: implement-level3-vector-retrieval
说明: Chunk 向量嵌入存储与检索操作

本模块提供 chunk 向量嵌入的存储和检索功能：
- insert_chunk_embeddings: 批量写入 embedding
- get_missing_embedding_chunk_ids: 查询缺失 embedding 的 chunk
- search_similar_chunks: pgvector 余弦相似度检索
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from src.storage.models import Chunk, ChunkEmbedding


def insert_chunk_embeddings(
    session: Session,
    run_id: str,
    embeddings: Iterable[tuple[int, list[float]]],
) -> int:
    """
    批量写入 chunk embedding

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        embeddings: (chunk_id, embedding_vector) 元组列表

    Returns:
        写入的记录数
    """
    session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.run_id == run_id))

    created_at = datetime.now().isoformat()
    rows = []
    for chunk_id, embedding_vector in embeddings:
        rows.append({
            "chunk_id": chunk_id,
            "run_id": run_id,
            "embedding_vector": json.dumps(embedding_vector),
            "created_at": created_at,
        })

    if rows:
        from sqlalchemy import insert
        session.execute(insert(ChunkEmbedding), rows)

    return len(rows)


def get_missing_embedding_chunk_ids(
    session: Session,
    run_id: str,
) -> list[int]:
    """
    查询缺失 embedding 的 chunk ID

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        缺失 embedding 的 chunk_id 列表
    """
    stmt = (
        select(Chunk.chunk_id)
        .where(Chunk.run_id == run_id)
        .where(
            Chunk.chunk_id.not_in(
                select(ChunkEmbedding.chunk_id).where(ChunkEmbedding.run_id == run_id)
            )
        )
    )
    result = session.execute(stmt)
    return [row[0] for row in result.fetchall()]


def get_chunk_embedding(
    session: Session,
    run_id: str,
    chunk_id: int,
) -> list[float] | None:
    """
    获取单个 chunk 的 embedding

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        chunk_id: chunk ID

    Returns:
        embedding 向量，如果不存在则返回 None
    """
    stmt = select(ChunkEmbedding.embedding_vector).where(
        ChunkEmbedding.run_id == run_id,
        ChunkEmbedding.chunk_id == chunk_id,
    )
    result = session.execute(stmt).scalar_one_or_none()
    if result:
        return json.loads(result)
    return None


def search_similar_chunks(
    session: Session,
    run_id: str,
    query_embedding: list[float],
    top_k: int = 5,
    similarity_threshold: float = 0.7,
    exclude_chunk_ids: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """
    使用 pgvector 进行向量相似度检索

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        query_embedding: 查询向量
        top_k: 返回的最大结果数
        similarity_threshold: 相似度阈值
        exclude_chunk_ids: 排除的 chunk ID 列表

    Returns:
        相似 chunk 列表，每个元素包含 chunk_id, similarity, text
    """
    query_vector_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    sql = text("""
        SELECT
            ce.chunk_id,
            c.text,
            1 - (ce.embedding_vector::vector <=> :query_vector::vector) as similarity
        FROM chunk_embeddings ce
        JOIN chunks c ON ce.chunk_id = c.chunk_id AND ce.run_id = c.run_id
        WHERE ce.run_id = :run_id
        AND ce.embedding_vector IS NOT NULL
        AND 1 - (ce.embedding_vector::vector <=> :query_vector::vector) >= :threshold
        ORDER BY similarity DESC
        LIMIT :limit
    """)

    params = {
        "run_id": run_id,
        "query_vector": query_vector_str,
        "threshold": similarity_threshold,
        "limit": top_k,
    }

    result = session.execute(sql, params)
    rows = result.fetchall()

    results = []
    for row in rows:
        chunk_id = row[0]
        if exclude_chunk_ids and chunk_id in exclude_chunk_ids:
            continue
        results.append({
            "chunk_id": chunk_id,
            "text": row[1],
            "similarity": float(row[2]),
        })

    return results


def has_embeddings(session: Session, run_id: str) -> bool:
    """
    检查是否存在 embedding 数据

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID

    Returns:
        是否存在 embedding 数据
    """
    stmt = select(ChunkEmbedding.chunk_id).where(ChunkEmbedding.run_id == run_id).limit(1)
    result = session.execute(stmt).scalar_one_or_none()
    return result is not None

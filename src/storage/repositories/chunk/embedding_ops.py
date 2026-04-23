"""
创建时间: 2026-04-10
创建者: TraeAI
任务: implement-level3-vector-retrieval
说明: Chunk 向量嵌入存储与检索操作

修改时间: 2026-04-21
修改者: Codex
任务: emotion-rag-evidence-provider
修改内容: Level3 检索补充 emotional_valence 元数据，供情绪 exemplar evidence 复用

本模块提供 chunk 向量嵌入的存储和检索功能：
- insert_chunk_embeddings: 批量写入 embedding
- get_missing_embedding_chunk_ids: 查询缺失 embedding 的 chunk
- search_similar_chunks: pgvector 余弦相似度检索
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.storage.models import Chunk, ChunkAnnotation, ChunkEmbedding


@dataclass(frozen=True)
class SimilarChunkRow:
    """
    创建时间: 2026-04-23
    任务: fix-coupling-review-findings
    说明: 收口 Level3 检索边界，避免向上游暴露匿名 dict，并统一使用具名字段访问。
    """

    chunk_id: int
    text: str
    similarity: float
    emotional_valence: str | None = None


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
        rows.append(
            {
                "chunk_id": chunk_id,
                "run_id": run_id,
                "embedding_vector": embedding_vector,
                "created_at": created_at,
            }
        )

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
        .where(Chunk.chunk_id.not_in(select(ChunkEmbedding.chunk_id).where(ChunkEmbedding.run_id == run_id)))
    )
    result = session.execute(stmt)
    return [row.chunk_id for row in result.fetchall()]


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
    if result is not None:
        return list(result)
    return None


def search_similar_chunks(
    session: Session,
    run_id: str,
    query_embedding: list[float],
    top_k: int = 5,
    similarity_threshold: float = 0.7,
    exclude_chunk_ids: Sequence[int] | None = None,
) -> list[SimilarChunkRow]:
    """
    使用 pgvector 进行向量相似度检索

    修改时间: 2026-04-21
    任务: emotion-rag-evidence-provider
    修改说明: 额外回传 chunk 的 emotional_valence，避免上层为了情绪 exemplar 再单独查一轮数据库。

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        query_embedding: 查询向量
        top_k: 返回的最大结果数
        similarity_threshold: 相似度阈值
        exclude_chunk_ids: 排除的 chunk ID 列表

    Returns:
        相似 chunk DTO 列表，每个元素包含 chunk_id, similarity, text, emotional_valence
    """
    run_scoped_chunks = (
        select(
            ChunkEmbedding.chunk_id.label("chunk_id"),
            Chunk.text.label("text"),
            ChunkEmbedding.embedding_vector.label("embedding_vector"),
            ChunkAnnotation.emotional_valence.label("emotional_valence"),
        )
        .join(
            Chunk,
            (ChunkEmbedding.chunk_id == Chunk.chunk_id) & (ChunkEmbedding.run_id == Chunk.run_id),
        )
        .outerjoin(
            ChunkAnnotation,
            (ChunkAnnotation.chunk_id == Chunk.chunk_id) & (ChunkAnnotation.run_id == Chunk.run_id),
        )
        .where(
            ChunkEmbedding.run_id == run_id,
            ChunkEmbedding.embedding_vector.is_not(None),
        )
    )
    if exclude_chunk_ids:
        run_scoped_chunks = run_scoped_chunks.where(ChunkEmbedding.chunk_id.not_in(list(exclude_chunk_ids)))

    run_scoped_chunks_subquery = run_scoped_chunks.subquery()
    similarity = (1 - run_scoped_chunks_subquery.c.embedding_vector.cosine_distance(query_embedding)).label(
        "similarity"
    )
    stmt = (
        select(
            run_scoped_chunks_subquery.c.chunk_id,
            run_scoped_chunks_subquery.c.text,
            run_scoped_chunks_subquery.c.emotional_valence,
            similarity,
        )
        .where(similarity >= similarity_threshold)
        .order_by(similarity.desc())
        .limit(top_k)
    )

    rows = session.execute(stmt).mappings().all()

    similar_chunks: list[SimilarChunkRow] = []
    for row in rows:
        similar_chunks.append(
            SimilarChunkRow(
                chunk_id=int(row["chunk_id"]),
                text=str(row["text"]),
                emotional_valence=str(row["emotional_valence"]) if row["emotional_valence"] is not None else None,
                similarity=float(row["similarity"]),
            )
        )
    return similar_chunks


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

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
- insert_paragraph_embeddings: 批量写入 paragraph embedding
- get_missing_embedding_chunk_ids: 查询缺失 embedding 的 chunk
- search_similar_chunks: pgvector 余弦相似度检索
- search_similar_paragraphs_within_chunks: 在候选 chunk 内检索 paragraph
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.storage.models import Chunk, ChunkAnnotation, ChunkEmbedding, ParagraphEmbedding


@dataclass(frozen=True)
class SimilarChunkRow:
    """
    创建时间: 2026-04-23
    任务: fix-coupling-review-findings
    说明: 收口 Level3 检索边界，避免向上游暴露匿名 dict，并统一使用具名字段访问。

    修改时间: 2026-04-23
    任务: level3-mention-retrieval
    修改说明: 增补 query_kind 与 mention 元数据字段，供上层标记 mention 级召回来源。
    """

    chunk_id: int
    text: str
    similarity: float
    emotional_valence: str | None = None
    query_kind: str = "chunk"
    mention_text: str | None = None
    mention_type: str | None = None
    matched_features: tuple[str, ...] = ()
    local_preview: str | None = None
    paragraph_index: int | None = None
    paragraph_similarity: float | None = None
    paragraph_start_char: int | None = None
    paragraph_end_char: int | None = None
    chunk_similarity: float | None = None


@dataclass(frozen=True)
class ParagraphEmbeddingRow:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph embedding 批量写入 DTO，所有字段使用具名属性，避免仓储层向上暴露匿名 dict。
    """

    chunk_id: int
    paragraph_index: int
    paragraph_text: str
    start_char: int
    end_char: int
    embedding_vector: list[float]


@dataclass(frozen=True)
class SimilarParagraphRow:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: 候选 chunk 内 paragraph rerank 的结果 DTO，用于回填 SimilarChunkRow 的局部 evidence 字段。
    """

    chunk_id: int
    paragraph_index: int
    paragraph_text: str
    start_char: int
    end_char: int
    similarity: float


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


def insert_paragraph_embeddings(
    session: Session,
    run_id: str,
    rows: Iterable[ParagraphEmbeddingRow],
) -> int:
    """
    批量写入 paragraph embedding。

    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: 每次 preprocess 重新生成当前 run_id 的 paragraph embeddings，
          与 chunk_embeddings 保持同一恢复语义。
    """
    session.execute(delete(ParagraphEmbedding).where(ParagraphEmbedding.run_id == run_id))

    created_at = datetime.now().isoformat()
    insert_rows = []
    for row in rows:
        insert_rows.append(
            {
                "run_id": run_id,
                "chunk_id": row.chunk_id,
                "paragraph_index": row.paragraph_index,
                "paragraph_text": row.paragraph_text,
                "start_char": row.start_char,
                "end_char": row.end_char,
                "embedding_vector": row.embedding_vector,
                "created_at": created_at,
            }
        )

    if insert_rows:
        from sqlalchemy import insert

        session.execute(insert(ParagraphEmbedding), insert_rows)

    return len(insert_rows)


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
    max_chunk_id: int | None = None,
) -> list[SimilarChunkRow]:
    """
    使用 pgvector 进行向量相似度检索

    修改时间: 2026-04-21
    任务: emotion-rag-evidence-provider
    修改说明: 额外回传 chunk 的 emotional_valence，避免上层为了情绪 exemplar 再单独查一轮数据库。

    修改时间: 2026-04-23
    任务: level3-history-cutoff
    修改说明: 增加 max_chunk_id 历史截止边界，确保增量取证不会召回未来 chunk。

    修改时间: 2026-04-24
    任务: level3-paragraph-rerank
    修改说明: 回填时改用 SQLAlchemy Row 具名属性访问，遵守数据库访问语义化约束。

    Args:
        session: SQLAlchemy Session 实例
        run_id: 运行ID
        query_embedding: 查询向量
        top_k: 返回的最大结果数
        similarity_threshold: 相似度阈值
        exclude_chunk_ids: 排除的 chunk ID 列表
        max_chunk_id: 允许召回的最大 chunk_id，None 表示不限制

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
    if max_chunk_id is not None:
        # 中文注释：历史截止必须下沉到 SQL 层，避免上游新增 query 形态时绕过时间边界。
        run_scoped_chunks = run_scoped_chunks.where(ChunkEmbedding.chunk_id <= max_chunk_id)

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

    rows = session.execute(stmt).all()

    similar_chunks: list[SimilarChunkRow] = []
    for row in rows:
        similar_chunks.append(
            SimilarChunkRow(
                chunk_id=int(row.chunk_id),
                text=str(row.text),
                emotional_valence=str(row.emotional_valence) if row.emotional_valence is not None else None,
                similarity=float(row.similarity),
            )
        )
    return similar_chunks


def search_similar_paragraphs_within_chunks(
    session: Session,
    run_id: str,
    query_embedding: list[float],
    chunk_ids: Sequence[int],
    top_k: int = 5,
    similarity_threshold: float = 0.7,
) -> list[SimilarParagraphRow]:
    """
    在候选 chunk 内检索相似 paragraph。

    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph embedding 只允许在 chunk 粗召回结果内使用，避免第一版误开全库 paragraph 检索。
    """
    scoped_chunk_ids = list(dict.fromkeys(int(chunk_id) for chunk_id in chunk_ids))
    if not scoped_chunk_ids:
        return []

    similarity = (1 - ParagraphEmbedding.embedding_vector.cosine_distance(query_embedding)).label("similarity")
    stmt = (
        select(
            ParagraphEmbedding.chunk_id,
            ParagraphEmbedding.paragraph_index,
            ParagraphEmbedding.paragraph_text,
            ParagraphEmbedding.start_char,
            ParagraphEmbedding.end_char,
            similarity,
        )
        .where(
            ParagraphEmbedding.run_id == run_id,
            ParagraphEmbedding.chunk_id.in_(scoped_chunk_ids),
            ParagraphEmbedding.embedding_vector.is_not(None),
            similarity >= similarity_threshold,
        )
        .order_by(similarity.desc())
        .limit(top_k)
    )

    rows = session.execute(stmt).all()
    return [
        SimilarParagraphRow(
            chunk_id=int(row.chunk_id),
            paragraph_index=int(row.paragraph_index),
            paragraph_text=str(row.paragraph_text),
            start_char=int(row.start_char),
            end_char=int(row.end_char),
            similarity=float(row.similarity),
        )
        for row in rows
    ]


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


def has_paragraph_embeddings(session: Session, run_id: str) -> bool:
    """
    检查指定 run_id 是否存在 paragraph embedding。

    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: Level3 可在 paragraph 数据缺失时显式回退 chunk evidence，但不能静默假装已完成 rerank。
    """
    stmt = select(ParagraphEmbedding.chunk_id).where(ParagraphEmbedding.run_id == run_id).limit(1)
    result = session.execute(stmt).scalar_one_or_none()
    return result is not None

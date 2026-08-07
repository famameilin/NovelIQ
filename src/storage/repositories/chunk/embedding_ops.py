"""
原文自然段向量存储与检索
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session

from src.storage.models import Chunk, ParagraphEmbedding


@dataclass(frozen=True)
class ParagraphEmbeddingRow:
    """2026-08-07 用于批量写入自然段文本定位与向量"""

    chunk_id: int
    paragraph_index: int
    paragraph_text: str
    local_start_char: int
    local_end_char: int
    global_start_char: int
    global_end_char: int
    embedding_vector: list[float]


@dataclass(frozen=True)
class SimilarParagraphRow:
    """2026-08-07 用于返回自然段语义定位结果与明确字符坐标"""

    chunk_id: int
    paragraph_index: int
    paragraph_text: str
    local_start_char: int
    local_end_char: int
    global_start_char: int
    global_end_char: int
    similarity: float


def insert_paragraph_embeddings(
    session: Session,
    run_id: str,
    rows: Iterable[ParagraphEmbeddingRow],
) -> int:
    """2026-08-07 用于重新生成当前 run 的全部自然段向量"""
    session.execute(delete(ParagraphEmbedding).where(ParagraphEmbedding.run_id == run_id))
    created_at = datetime.now().isoformat()
    insert_rows = [
        {
            "run_id": run_id,
            "chunk_id": row.chunk_id,
            "paragraph_index": row.paragraph_index,
            "paragraph_text": row.paragraph_text,
            "local_start_char": row.local_start_char,
            "local_end_char": row.local_end_char,
            "global_start_char": row.global_start_char,
            "global_end_char": row.global_end_char,
            "embedding_vector": row.embedding_vector,
            "created_at": created_at,
        }
        for row in rows
    ]
    if insert_rows:
        from sqlalchemy import insert

        session.execute(insert(ParagraphEmbedding), insert_rows)
    return len(insert_rows)


def search_similar_paragraphs_within_chunks(
    session: Session,
    run_id: str,
    query_embedding: list[float],
    chunk_ids: Sequence[int],
    top_k: int = 5,
    similarity_threshold: float = 0.7,
) -> list[SimilarParagraphRow]:
    """2026-08-07 用于在指定候选 chunk 内选取每个 chunk 最佳语义自然段"""
    scoped_chunk_ids = list(dict.fromkeys(int(chunk_id) for chunk_id in chunk_ids))
    if not scoped_chunk_ids:
        return []
    similarity_expr = 1 - ParagraphEmbedding.embedding_vector.cosine_distance(query_embedding)
    ranked_candidates = (
        select(
            ParagraphEmbedding.chunk_id,
            ParagraphEmbedding.paragraph_index,
            ParagraphEmbedding.paragraph_text,
            ParagraphEmbedding.local_start_char,
            ParagraphEmbedding.local_end_char,
            ParagraphEmbedding.global_start_char,
            ParagraphEmbedding.global_end_char,
            similarity_expr.label("similarity"),
            func.row_number()
            .over(
                partition_by=ParagraphEmbedding.chunk_id,
                order_by=(similarity_expr.desc(), ParagraphEmbedding.paragraph_index.asc()),
            )
            .label("paragraph_rank"),
        )
        .where(
            ParagraphEmbedding.run_id == run_id,
            ParagraphEmbedding.chunk_id.in_(scoped_chunk_ids),
            ParagraphEmbedding.embedding_vector.is_not(None),
            similarity_expr >= similarity_threshold,
        )
        .subquery()
    )
    statement = (
        select(
            ranked_candidates.c.chunk_id,
            ranked_candidates.c.paragraph_index,
            ranked_candidates.c.paragraph_text,
            ranked_candidates.c.local_start_char,
            ranked_candidates.c.local_end_char,
            ranked_candidates.c.global_start_char,
            ranked_candidates.c.global_end_char,
            ranked_candidates.c.similarity,
        )
        .where(ranked_candidates.c.paragraph_rank == 1)
        .order_by(ranked_candidates.c.similarity.desc(), ranked_candidates.c.chunk_id.asc())
        .limit(top_k)
    )
    return [_similar_paragraph_row(row) for row in session.execute(statement).all()]


def search_similar_paragraphs(
    session: Session,
    run_id: str,
    query_embedding: list[float],
    top_k: int = 5,
    similarity_threshold: float = 0.7,
    exclude_chunk_ids: Sequence[int] | None = None,
    min_chunk_id: int | None = None,
    max_chunk_id: int | None = None,
) -> list[SimilarParagraphRow]:
    """2026-08-07 用于在同 run 原文自然段中执行有位置边界的 pgvector 检索"""
    similarity_expr = 1 - ParagraphEmbedding.embedding_vector.cosine_distance(query_embedding)
    statement = select(
        ParagraphEmbedding.chunk_id,
        ParagraphEmbedding.paragraph_index,
        ParagraphEmbedding.paragraph_text,
        ParagraphEmbedding.local_start_char,
        ParagraphEmbedding.local_end_char,
        ParagraphEmbedding.global_start_char,
        ParagraphEmbedding.global_end_char,
        similarity_expr.label("similarity"),
    ).where(
        ParagraphEmbedding.run_id == run_id,
        ParagraphEmbedding.embedding_vector.is_not(None),
        similarity_expr >= similarity_threshold,
    )
    if exclude_chunk_ids:
        statement = statement.where(ParagraphEmbedding.chunk_id.not_in(list(exclude_chunk_ids)))
    if min_chunk_id is not None:
        statement = statement.where(ParagraphEmbedding.chunk_id >= min_chunk_id)
    if max_chunk_id is not None:
        statement = statement.where(ParagraphEmbedding.chunk_id <= max_chunk_id)
    statement = statement.order_by(
        similarity_expr.desc(),
        ParagraphEmbedding.chunk_id.asc(),
        ParagraphEmbedding.paragraph_index.asc(),
    ).limit(top_k)
    return [_similar_paragraph_row(row) for row in session.execute(statement).all()]


def _similar_paragraph_row(row: Any) -> SimilarParagraphRow:
    """2026-08-07 用于把 SQLAlchemy 结果行转换为自然段语义 DTO"""
    return SimilarParagraphRow(
        chunk_id=int(row.chunk_id),
        paragraph_index=int(row.paragraph_index),
        paragraph_text=str(row.paragraph_text),
        local_start_char=int(row.local_start_char),
        local_end_char=int(row.local_end_char),
        global_start_char=int(row.global_start_char),
        global_end_char=int(row.global_end_char),
        similarity=float(row.similarity),
    )


def has_paragraph_embeddings(session: Session, run_id: str) -> bool:
    """2026-08-07 用于检查指定 run 是否存在自然段向量"""
    statement = select(ParagraphEmbedding.chunk_id).where(
        ParagraphEmbedding.run_id == run_id
    ).limit(1)
    return session.execute(statement).scalar_one_or_none() is not None


def get_incomplete_paragraph_embedding_chunk_ids(session: Session, run_id: str) -> list[int]:
    """2026-08-07 用于发现缺失不连续空向量或坐标不完整的自然段数据"""
    paragraph_exists = exists().where(
        (ParagraphEmbedding.run_id == Chunk.run_id)
        & (ParagraphEmbedding.chunk_id == Chunk.chunk_id)
    )
    missing_statement = (
        select(Chunk.chunk_id)
        .where(Chunk.run_id == run_id)
        .where(Chunk.text.is_not(None))
        .where(~paragraph_exists)
    )
    missing_chunk_ids = {
        int(row.chunk_id)
        for row in session.execute(missing_statement).all()
    }
    count_label = func.count(ParagraphEmbedding.paragraph_index)
    max_index_label = func.max(ParagraphEmbedding.paragraph_index)
    min_index_label = func.min(ParagraphEmbedding.paragraph_index)
    gapped_statement = (
        select(ParagraphEmbedding.chunk_id)
        .where(ParagraphEmbedding.run_id == run_id)
        .group_by(ParagraphEmbedding.chunk_id)
        .having(or_(min_index_label != 0, count_label != max_index_label + 1))
    )
    gapped_chunk_ids = {
        int(row.chunk_id)
        for row in session.execute(gapped_statement).all()
    }
    null_statement = (
        select(ParagraphEmbedding.chunk_id)
        .where(ParagraphEmbedding.run_id == run_id)
        .where(
            or_(
                ParagraphEmbedding.embedding_vector.is_(None),
                ParagraphEmbedding.local_start_char.is_(None),
                ParagraphEmbedding.local_end_char.is_(None),
                ParagraphEmbedding.global_start_char.is_(None),
                ParagraphEmbedding.global_end_char.is_(None),
            )
        )
        .group_by(ParagraphEmbedding.chunk_id)
    )
    null_chunk_ids = {
        int(row.chunk_id)
        for row in session.execute(null_statement).all()
    }
    return sorted(missing_chunk_ids | gapped_chunk_ids | null_chunk_ids)

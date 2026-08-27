"""
原文自然段向量存储与检索
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from src.config import settings
from src.storage.models import Paragraph, ParagraphEmbedding


@dataclass(frozen=True)
class ParagraphEmbeddingRow:
    """2026-08-14 用于批量写入自然段向量（二期段落化：段落身份 + 向量）"""

    paragraph_id: int
    embedding_vector: list[float]


@dataclass(frozen=True)
class SimilarParagraphRow:
    """2026-08-14 用于返回自然段语义定位结果（JOIN paragraphs 取身份与坐标）"""

    paragraph_id: int
    chapter_id: int
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
    """2026-08-14 用于重新生成当前 run 的全部自然段向量

    先删后插（同 run 不可重跑前序阶段的语义）；embedding_model_key /
    embedding_dimension 从 settings.models.paragraph_embedding 读取；
    source_content_hash 对照 paragraphs 表按 paragraph_id 一次性查询，
    缺失段落返回 None（不伪造溯源）。
    """
    materialized = list(rows)
    session.execute(delete(ParagraphEmbedding).where(ParagraphEmbedding.run_id == run_id))
    if not materialized:
        return 0
    paragraph_ids = [row.paragraph_id for row in materialized]
    hash_rows = session.execute(
        select(Paragraph.paragraph_id, Paragraph.content_hash).where(
            Paragraph.run_id == run_id,
            Paragraph.paragraph_id.in_(paragraph_ids),
        )
    ).all()
    content_hash_by_paragraph = {int(row.paragraph_id): str(row.content_hash) for row in hash_rows}
    model_settings = settings.models.paragraph_embedding
    created_at = datetime.now().isoformat()
    insert_rows = [
        {
            "run_id": run_id,
            "paragraph_id": row.paragraph_id,
            "embedding_vector": row.embedding_vector,
            "embedding_model_key": getattr(model_settings, "model", None),
            "embedding_dimension": getattr(model_settings, "embedding_dim", None),
            "source_content_hash": content_hash_by_paragraph.get(row.paragraph_id),
            "created_at": created_at,
        }
        for row in materialized
    ]
    session.execute(insert(ParagraphEmbedding), insert_rows)
    return len(insert_rows)


def search_similar_paragraphs(
    session: Session,
    run_id: str,
    query_embedding: list[float],
    top_k: int = 5,
    similarity_threshold: float = 0.7,
    exclude_paragraph_ids: Sequence[int] | None = None,
    min_paragraph_id: int | None = None,
    max_paragraph_id: int | None = None,
) -> list[SimilarParagraphRow]:
    """2026-08-14 同 run 原文自然段 pgvector 检索（段落边界）。

    2026-08-13 P1-1 裸余弦 ``<=>``（升序）命中 HNSW，阈值 distance<=1-threshold；
    2026-08-14 二期 JOIN paragraphs（run_id/paragraph_id 对齐），以 paragraphs 为事实源。
    """
    distance_expr = ParagraphEmbedding.embedding_vector.cosine_distance(query_embedding)
    similarity_expr = 1 - distance_expr
    # round 避免 1 - 0.7 = 0.30000000000000004 的浮点噪声进入 SQL 字面量
    max_distance = round(1.0 - similarity_threshold, 6)
    statement = (
        select(
            Paragraph.paragraph_id,
            Paragraph.chapter_id,
            Paragraph.text.label("paragraph_text"),
            Paragraph.local_start_char,
            Paragraph.local_end_char,
            Paragraph.global_start_char,
            Paragraph.global_end_char,
            similarity_expr.label("similarity"),
        )
        .join(
            Paragraph,
            (ParagraphEmbedding.run_id == Paragraph.run_id)
            & (ParagraphEmbedding.paragraph_id == Paragraph.paragraph_id),
        )
        .where(
            ParagraphEmbedding.run_id == run_id,
            ParagraphEmbedding.embedding_vector.is_not(None),
            distance_expr <= max_distance,
        )
    )
    if exclude_paragraph_ids:
        statement = statement.where(Paragraph.paragraph_id.not_in(list(exclude_paragraph_ids)))
    if min_paragraph_id is not None:
        statement = statement.where(Paragraph.paragraph_id >= min_paragraph_id)
    if max_paragraph_id is not None:
        statement = statement.where(Paragraph.paragraph_id <= max_paragraph_id)
    statement = statement.order_by(
        distance_expr.asc(),
        Paragraph.paragraph_id.asc(),
    ).limit(top_k)
    return [_similar_paragraph_row(row) for row in session.execute(statement).all()]


def _similar_paragraph_row(row: Any) -> SimilarParagraphRow:
    """2026-08-14 用于把 SQLAlchemy 结果行转换为自然段语义 DTO"""
    return SimilarParagraphRow(
        paragraph_id=int(row.paragraph_id),
        chapter_id=int(row.chapter_id),
        paragraph_text=str(row.paragraph_text),
        local_start_char=int(row.local_start_char),
        local_end_char=int(row.local_end_char),
        global_start_char=int(row.global_start_char),
        global_end_char=int(row.global_end_char),
        similarity=float(row.similarity),
    )


def has_paragraph_embeddings(session: Session, run_id: str) -> bool:
    """2026-08-07 用于检查指定 run 是否存在自然段向量"""
    statement = select(ParagraphEmbedding.paragraph_id).where(ParagraphEmbedding.run_id == run_id).limit(1)
    return session.execute(statement).scalar_one_or_none() is not None


def get_incomplete_paragraph_embedding_paragraph_ids(session: Session, run_id: str) -> list[int]:
    """2026-08-14 用于发现"有段落但无可用向量"的缺口段落 ID 列表

    二期段落化：段落身份以 paragraphs 表为准，不再按 chunk 聚合判定。
    缺口包含两类：
    1. 段落存在但没有 embedding 行（paragraphs LEFT JOIN paragraph_embeddings）；
    2. embedding 行存在但向量为空（embedding_vector IS NULL）。

    chunk 级缺口（某 chunk 完全无向量）由上述段落级缺口自然覆盖
    （该 chunk 的每个段落都会出现在结果中）。返回排序后的段落 ID 列表。
    """
    missing_statement = (
        select(Paragraph.paragraph_id)
        .outerjoin(
            ParagraphEmbedding,
            (ParagraphEmbedding.run_id == Paragraph.run_id)
            & (ParagraphEmbedding.paragraph_id == Paragraph.paragraph_id),
        )
        .where(
            Paragraph.run_id == run_id,
            ParagraphEmbedding.run_id.is_(None),
        )
    )
    missing_paragraph_ids = {int(row.paragraph_id) for row in session.execute(missing_statement).all()}
    null_vector_statement = select(ParagraphEmbedding.paragraph_id).where(
        ParagraphEmbedding.run_id == run_id,
        ParagraphEmbedding.embedding_vector.is_(None),
    )
    null_vector_paragraph_ids = {int(row.paragraph_id) for row in session.execute(null_vector_statement).all()}
    return sorted(missing_paragraph_ids | null_vector_paragraph_ids)

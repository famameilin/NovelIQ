"原文自然段向量存储与检索"

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import cast, delete, func, insert, select
from sqlalchemy.orm import Session

from src.config import settings
from src.storage.models import Chapter, Paragraph, ParagraphFeature
from src.storage.records.embedding_ops import ParagraphEmbeddingRow, SimilarParagraphRow
from src.storage.repositories.paragraph.reader import join_chapter_body, paragraph_projection
from src.storage.vector_schema import hnsw_index_uses_halfvec

#: 语义向量 feature_code（paragraph_features 封闭计算种类）
FEATURE_SEMANTIC_VECTOR = "semantic_vector"


def insert_paragraph_embeddings(
    session: Session,
    run_id: str,
    rows: Iterable[ParagraphEmbeddingRow],
    embedding_dimension: int | None = None,
) -> int:
    "用于重新生成当前 run 的全部自然段向量"
    materialized = list(rows)
    session.execute(
        delete(ParagraphFeature).where(
            ParagraphFeature.run_id == run_id,
            ParagraphFeature.feature_code == FEATURE_SEMANTIC_VECTOR,
        )
    )
    if not materialized:
        return 0
    if embedding_dimension is None or embedding_dimension <= 0:
        # 维度不再逐行冗余保存，缺少实测维度时无法校验运行模型合同
        raise ValueError(
            "paragraph embedding 写入失败：embedding_dimension 必须为探测到的正维度，"
            f"run_id={run_id} embedding_dimension={embedding_dimension}"
        )
    model_settings = settings.models.paragraph_embedding
    model_key = getattr(model_settings, "model", None)
    if not model_key:
        raise ValueError(
            "paragraph embedding 写入失败：settings.models.paragraph_embedding.model 未配置，"
            f"无法登记运行模型合同 run_id={run_id}"
        )
    created_at = datetime.now(UTC).replace(tzinfo=None)
    session.execute(
        insert(ParagraphFeature),
        [
            {
                "run_id": run_id,
                "paragraph_id": row.paragraph_id,
                "feature_code": FEATURE_SEMANTIC_VECTOR,
                "vector_value": row.embedding_vector,
                "created_at": created_at,
            }
            for row in materialized
        ],
    )
    return len(materialized)


def search_similar_paragraphs(
    session: Session,
    run_id: str,
    query_embedding: list[float],
    top_k: int = 5,
    similarity_threshold: float = 0.7,
    exclude_paragraph_ids: Sequence[int] | None = None,
    min_paragraph_id: int | None = None,
    max_paragraph_id: int | None = None,
    before_chapter_sequence: int | None = None,
    after_chapter_sequence: int | None = None,
) -> list[SimilarParagraphRow]:
    "同 run 原文自然段 pgvector 检索（段落边界）"
    dimension = len(query_embedding)
    if hnsw_index_uses_halfvec(dimension):
        distance_expr = cast(ParagraphFeature.vector_value, HALFVEC(dimension)).cosine_distance(query_embedding)
    else:
        distance_expr = ParagraphFeature.vector_value.cosine_distance(query_embedding)
    similarity_expr = 1 - distance_expr
    # round 避免 1 - 0.7 = 0.30000000000000004 的浮点噪声进入 SQL 字面量
    max_distance = round(1.0 - similarity_threshold, 6)
    statement = join_chapter_body(
        select(
            *paragraph_projection(text_label="paragraph_text"),
            similarity_expr.label("similarity"),
        )
        .select_from(ParagraphFeature)
        .join(
            Paragraph,
            (ParagraphFeature.run_id == Paragraph.run_id) & (ParagraphFeature.paragraph_id == Paragraph.paragraph_id),
        )
    ).where(
        ParagraphFeature.run_id == run_id,
        ParagraphFeature.feature_code == FEATURE_SEMANTIC_VECTOR,
        ParagraphFeature.vector_value.is_not(None),
        # 与 HNSW 部分索引同谓词（index 只为固定维度表达式建立）：
        # 显式限定维度让规划器可以命中该表达式索引，避免全表扫描
        func.vector_dims(ParagraphFeature.vector_value) == dimension,
        distance_expr <= max_distance,
    )
    if exclude_paragraph_ids:
        statement = statement.where(Paragraph.paragraph_id.not_in(list(exclude_paragraph_ids)))
    if min_paragraph_id is not None:
        statement = statement.where(Paragraph.paragraph_id >= min_paragraph_id)
    if max_paragraph_id is not None:
        statement = statement.where(Paragraph.paragraph_id <= max_paragraph_id)
    if before_chapter_sequence is not None:
        statement = statement.where(Chapter.sequence < before_chapter_sequence)
    if after_chapter_sequence is not None:
        statement = statement.where(Chapter.sequence > after_chapter_sequence)
    statement = statement.order_by(
        distance_expr.asc(),
        Paragraph.paragraph_id.asc(),
    ).limit(top_k)
    return [_similar_paragraph_row(row) for row in session.execute(statement).all()]


def _similar_paragraph_row(row: Any) -> SimilarParagraphRow:
    "用于把 SQLAlchemy 结果行转换为自然段语义 DTO"
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
    "用于检查指定 run 是否存在自然段向量"
    statement = (
        select(ParagraphFeature.paragraph_id)
        .where(
            ParagraphFeature.run_id == run_id,
            ParagraphFeature.feature_code == FEATURE_SEMANTIC_VECTOR,
        )
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none() is not None


def get_incomplete_paragraph_embedding_paragraph_ids(session: Session, run_id: str) -> list[int]:
    '用于发现"有段落但无可用向量"的缺口段落 ID 列表'
    missing_statement = (
        select(Paragraph.paragraph_id)
        .select_from(Paragraph)
        .outerjoin(
            ParagraphFeature,
            (ParagraphFeature.run_id == Paragraph.run_id)
            & (ParagraphFeature.paragraph_id == Paragraph.paragraph_id)
            & (ParagraphFeature.feature_code == FEATURE_SEMANTIC_VECTOR),
        )
        .where(
            Paragraph.run_id == run_id,
            ParagraphFeature.run_id.is_(None),
        )
    )
    missing_paragraph_ids = {int(row.paragraph_id) for row in session.execute(missing_statement).all()}
    null_vector_statement = select(ParagraphFeature.paragraph_id).where(
        ParagraphFeature.run_id == run_id,
        ParagraphFeature.feature_code == FEATURE_SEMANTIC_VECTOR,
        ParagraphFeature.vector_value.is_(None),
    )
    null_vector_paragraph_ids = {int(row.paragraph_id) for row in session.execute(null_vector_statement).all()}
    return sorted(missing_paragraph_ids | null_vector_paragraph_ids)

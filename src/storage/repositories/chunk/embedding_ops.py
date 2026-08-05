"""
Chunk 向量嵌入存储与检索操作

Level3 检索补充 emotional_valence 元数据，供情绪 exemplar evidence 复用

本模块提供 chunk 向量嵌入的存储和检索功能：
- insert_chunk_embeddings: 批量写入 embedding
- insert_paragraph_embeddings: 批量写入 paragraph embedding
- get_missing_embedding_chunk_ids: 查询缺失 embedding 的 chunk
- get_incomplete_paragraph_embedding_chunk_ids: 查询 paragraph embedding 不完整的 chunk
- search_similar_chunks: pgvector 余弦相似度检索
- search_similar_paragraphs_within_chunks: 在候选 chunk 内检索 paragraph
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session

from src.storage.models import Chunk, ChunkEmbedding, ParagraphEmbedding


@dataclass(frozen=True)
class SimilarChunkRow:
    """
    收口 Level3 检索边界，避免向上游暴露匿名 dict，并统一使用具名字段访问

    增补 query_kind 与 mention 元数据字段，供上层标记 mention 级召回来源

    增补确定性 mention rerank 的可解释字段，保留原始语义分并记录加权原因

    显式拆分 chunk/paragraph/business/final 四类分数，避免 `similarity` 在多阶段 rerank 中持续变义

    增补 LLM mention source、query variant 与模型 rerank 观察字段，保持上层 metadata 合同可冻结
    """

    chunk_id: int
    text: str
    similarity: float
    emotional_valence: str | None = None
    query_kind: str = "chunk"
    mention_text: str | None = None
    mention_type: str | None = None
    matched_features: tuple[str, ...] = ()
    mention_source: str | None = None
    mention_confidence: float | None = None
    query_variant: str | None = None
    local_preview: str | None = None
    paragraph_index: int | None = None
    paragraph_local_start_char: int | None = None
    paragraph_local_end_char: int | None = None
    paragraph_global_start_char: int | None = None
    paragraph_global_end_char: int | None = None
    chunk_semantic_score: float | None = None
    paragraph_semantic_score: float | None = None
    business_rerank_score: float | None = None
    model_rerank_score: float | None = None
    model_rerank_reason: str | None = None
    model_confidence: float | None = None
    model_rerank_enabled: bool = False
    rerank_source: str | None = None
    final_rank_score: float | None = None
    feature_overlap: tuple[str, ...] = ()
    active_entity_bonus: float = 0.0
    identity_clue_bonus: float = 0.0
    candidate_related_bonus: float = 0.0
    time_decay: float = 0.0
    rerank_penalty: float = 0.0
    penalties: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParagraphEmbeddingRow:
    """
    paragraph embedding 批量写入 DTO，所有字段使用具名属性，避免仓储层向上暴露匿名 dict

    同时携带 chunk 内 local offset 与 run 级 global offset，避免后续只能通过 chunk 表回推全文坐标
    """

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
    """
    候选 chunk 内 paragraph rerank 的结果 DTO，用于回填 SimilarChunkRow 的局部 evidence 字段

    查询结果同时暴露 local/global offset，方便上游在保持兼容字段的同时新增全文定位能力
    """

    chunk_id: int
    paragraph_index: int
    paragraph_text: str
    local_start_char: int
    local_end_char: int
    global_start_char: int
    global_end_char: int
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
    批量写入 paragraph embedding

    每次 preprocess 重新生成当前 run_id 的 paragraph embeddings，
          与 chunk_embeddings 保持同一恢复语义
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
                "local_start_char": row.local_start_char,
                "local_end_char": row.local_end_char,
                "global_start_char": row.global_start_char,
                "global_end_char": row.global_end_char,
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

    额外回传 chunk 的 emotional_valence，避免上层为了情绪 exemplar 再单独查一轮数据库

    增加 max_chunk_id 历史截止边界，确保增量取证不会召回未来 chunk

    回填时改用 SQLAlchemy Row 具名属性访问，遵守数据库访问语义化约束

    初始化显式分数字段，后续 paragraph / business rerank 在不丢失 chunk 语义分的前提下继续叠加

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
        )
        .join(
            Chunk,
            (ChunkEmbedding.chunk_id == Chunk.chunk_id) & (ChunkEmbedding.run_id == Chunk.run_id),
        )
        .where(
            ChunkEmbedding.run_id == run_id,
            ChunkEmbedding.embedding_vector.is_not(None),
        )
    )
    if exclude_chunk_ids:
        run_scoped_chunks = run_scoped_chunks.where(ChunkEmbedding.chunk_id.not_in(list(exclude_chunk_ids)))
    if max_chunk_id is not None:
        # 历史截止必须下沉到 SQL 层，避免上游新增 query 形态时绕过时间边界
        run_scoped_chunks = run_scoped_chunks.where(ChunkEmbedding.chunk_id <= max_chunk_id)

    run_scoped_chunks_subquery = run_scoped_chunks.subquery()
    similarity = (1 - run_scoped_chunks_subquery.c.embedding_vector.cosine_distance(query_embedding)).label(
        "similarity"
    )
    stmt = (
        select(
            run_scoped_chunks_subquery.c.chunk_id,
            run_scoped_chunks_subquery.c.text,
            similarity,
        )
        .where(similarity >= similarity_threshold)
        .order_by(similarity.desc())
        .limit(top_k)
    )

    rows = session.execute(stmt).all()
    from src.storage.repositories.annotation import AnnotationRepository

    emotional_valence_by_chunk = {
        row.chunk_id: row.emotional_valence
        for row in AnnotationRepository(session).fetch_chunk_annotations_full(run_id)
    }

    similar_chunks: list[SimilarChunkRow] = []
    for row in rows:
        similar_chunks.append(
            SimilarChunkRow(
                chunk_id=int(row.chunk_id),
                text=str(row.text),
                emotional_valence=emotional_valence_by_chunk.get(int(row.chunk_id)),
                similarity=float(row.similarity),
                chunk_semantic_score=float(row.similarity),
                final_rank_score=float(row.similarity),
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
    在候选 chunk 内检索相似 paragraph

    paragraph embedding 只允许在 chunk 粗召回结果内使用，避免第一版误开全库 paragraph 检索

    先在每个候选 chunk 内选出最佳 paragraph，再做 chunk 级全局排序，
              避免全局 LIMIT 让部分候选 chunk 完全失去 paragraph rerank 机会

    返回值改为显式 local/global offset，不再继续暴露歧义的 start_char/end_char 合同
    """
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
    stmt = (
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
        # 必须先按 chunk_id 选 best paragraph，再截断 top_k，
        # 否则某个 chunk 的多个高分 paragraph 会挤掉其他候选 chunk
        .where(ranked_candidates.c.paragraph_rank == 1)
        .order_by(ranked_candidates.c.similarity.desc(), ranked_candidates.c.chunk_id.asc())
        .limit(top_k)
    )

    rows = session.execute(stmt).all()
    return [
        SimilarParagraphRow(
            chunk_id=int(row.chunk_id),
            paragraph_index=int(row.paragraph_index),
            paragraph_text=str(row.paragraph_text),
            local_start_char=int(row.local_start_char),
            local_end_char=int(row.local_end_char),
            global_start_char=int(row.global_start_char),
            global_end_char=int(row.global_end_char),
            similarity=float(row.similarity),
        )
        for row in rows
    ]


def search_similar_paragraphs(
    session: Session,
    run_id: str,
    query_embedding: list[float],
    top_k: int = 5,
    similarity_threshold: float = 0.7,
    exclude_chunk_ids: Sequence[int] | None = None,
    max_chunk_id: int | None = None,
) -> list[SimilarParagraphRow]:
    """
    Run 级自然段向量检索（RAG 粒度固定为一个自然段）

    不再做 chunk 粗召回 + paragraph 重排，直接在 run 内全库段落检索；
    证据单元就是一个自然段，其他粒度不再参与召回

    支持 exclude_chunk_ids 与 max_chunk_id 历史截止边界，语义与旧 chunk 召回一致
    """
    similarity_expr = 1 - ParagraphEmbedding.embedding_vector.cosine_distance(query_embedding)
    stmt = select(
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
        stmt = stmt.where(ParagraphEmbedding.chunk_id.not_in(list(exclude_chunk_ids)))
    if max_chunk_id is not None:
        stmt = stmt.where(ParagraphEmbedding.chunk_id <= max_chunk_id)
    stmt = stmt.order_by(
        similarity_expr.desc(),
        ParagraphEmbedding.chunk_id.asc(),
        ParagraphEmbedding.paragraph_index.asc(),
    ).limit(top_k)

    rows = session.execute(stmt).all()
    return [
        SimilarParagraphRow(
            chunk_id=int(row.chunk_id),
            paragraph_index=int(row.paragraph_index),
            paragraph_text=str(row.paragraph_text),
            local_start_char=int(row.local_start_char),
            local_end_char=int(row.local_end_char),
            global_start_char=int(row.global_start_char),
            global_end_char=int(row.global_end_char),
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
    检查指定 run_id 是否存在 paragraph embedding

    Level3 可在 paragraph 数据缺失时显式回退 chunk evidence，但不能静默假装已完成 rerank
    """
    stmt = select(ParagraphEmbedding.chunk_id).where(ParagraphEmbedding.run_id == run_id).limit(1)
    result = session.execute(stmt).scalar_one_or_none()
    return result is not None


def get_incomplete_paragraph_embedding_chunk_ids(session: Session, run_id: str) -> list[int]:
    """
    查询 paragraph embedding 不完整的 chunk ID

    readiness 不只检查是否有任意 paragraph row，还要发现：
          1. 某个 chunk 完全没有 paragraph embedding；
          2. 某个 chunk 的 paragraph_index 没有从 0 开始连续落库

    将 `embedding_vector IS NULL` 视为不完整，避免 readiness 通过但检索阶段被 `IS NOT NULL` 过滤掉

    local/global 任一 offset 缺失都视为不完整，避免全文定位字段只升级了一半
    """
    paragraph_exists = exists().where(
        (ParagraphEmbedding.run_id == Chunk.run_id) & (ParagraphEmbedding.chunk_id == Chunk.chunk_id)
    )
    missing_stmt = (
        select(Chunk.chunk_id)
        .where(Chunk.run_id == run_id)
        .where(Chunk.text.is_not(None))
        .where(~paragraph_exists)
    )
    missing_chunk_ids = {int(row.chunk_id) for row in session.execute(missing_stmt).all()}

    count_label = func.count(ParagraphEmbedding.paragraph_index)
    max_index_label = func.max(ParagraphEmbedding.paragraph_index)
    min_index_label = func.min(ParagraphEmbedding.paragraph_index)
    gapped_stmt = (
        select(ParagraphEmbedding.chunk_id)
        .where(ParagraphEmbedding.run_id == run_id)
        .group_by(ParagraphEmbedding.chunk_id)
        .having(or_(min_index_label != 0, count_label != max_index_label + 1))
    )
    gapped_chunk_ids = {int(row.chunk_id) for row in session.execute(gapped_stmt).all()}

    null_vector_stmt = (
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
    null_vector_chunk_ids = {int(row.chunk_id) for row in session.execute(null_vector_stmt).all()}

    return sorted(missing_chunk_ids | gapped_chunk_ids | null_vector_chunk_ids)

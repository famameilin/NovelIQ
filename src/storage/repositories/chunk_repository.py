"""
实现 ChunkRepository 类，管理文本分块的存储和检索

添加查询方法 fetch_chunk_styles_full, fetch_chunk_cultures_full, fetch_chunk_topics_agg, fetch_chunk_counts

从 sqlite3.Connection 迁移到 SQLAlchemy Session，使用 ORM 查询替代原生 SQL

将 ChunkStyleData 数据类移至 chunk/style_data.py
将 style/culture/topic 操作移至子模块

修复 fetch_chunk_cultures_full 返回类型为 List[Tuple[int, float]]

fetch_chunk_styles_full 返回 Sequence[Row] 支持字段名访问

删除 culture 兼容接口，imagery_lexicon_density 统一走 ChunkStyle 主仓储链路
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.chunking.chunker import Chunk
from src.config import settings
from src.storage.models import Chunk as ChunkModel
from src.storage.models import ChunkSummary
from src.storage.repositories.base import BaseRepository
from src.storage.repositories.chunk import (
    ChunkStyleData,
    clear_chunk_topics,
    fetch_chunk_imagery_lexicon_densities,
    fetch_chunk_styles,
    fetch_chunk_styles_full,
    fetch_chunk_topics_agg,
    get_incomplete_paragraph_embedding_chunk_ids,
    has_paragraph_embeddings,
    insert_chunk_style,
    insert_chunk_topics,
)
from src.storage.vector_schema import validate_paragraph_embeddings_schema


class ChunkRepository(BaseRepository["ChunkModel"]):
    """
    分块数据 Repository

    管理文本分块的存储和检索，支持 run_id 过滤

    从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def __init__(self, session: Session):
        """
        初始化 ChunkRepository

        Args:
            session: SQLAlchemy Session 实例
        """
        super().__init__(session)

    def insert_chunks(self, run_id: str, chunks: Sequence[Chunk]) -> None:
        """
        批量插入分块数据

        插入前先删除该 run_id 的旧数据

        将 chunk 的真实全文起止坐标一并持久化，避免后续 paragraph global offset 只能依赖内存对象

        chapter_id 直接取解析器分配的章节编号（chunk.chapter_id），与 chapters 表一一对应

        2026-08-14 D8 契约：chunks 是 graph_facts/entity_state_versions/dialogue_records/
        case_pool_cases/foreshadowing_threads 等下游表的 FK 父表（ON DELETE CASCADE），
        先删后插会级联清空同 run 的全部下游数据。**同 run 不允许重跑前序阶段**——
        重分析必须使用新 run_id（reanalysis 每次创建新 run）；若确需重建，应先显式
        delete_run 清理整个 run。
        """
        self.session.execute(delete(ChunkModel).where(ChunkModel.run_id == run_id))
        models = []
        for chunk in chunks:
            models.append(
                ChunkModel(
                    chunk_id=chunk.index,
                    chapter_id=chunk.chapter_id,
                    char_offset=chunk.start,
                    char_end_offset=chunk.end,
                    text=chunk.text,
                    run_id=run_id,
                )
            )
        self.session.bulk_save_objects(models)

    def fetch_chunks_with_chapter(self, run_id: str) -> list[tuple[int, int, str]]:
        """
        2026-08-02 用于按原始顺序读取标注 dispatcher 所需的 chunk 章节与文本
        """
        stmt = (
            select(ChunkModel.chunk_id, ChunkModel.chapter_id, ChunkModel.text)
            .where(ChunkModel.run_id == run_id)
            .order_by(ChunkModel.chunk_id)
        )
        rows = self.session.execute(stmt).all()
        return [
            (row.chunk_id, row.chapter_id, row.text)
            for row in rows
        ]

    def fetch_chunk_texts(self, run_id: str) -> list[tuple[int, str]]:
        """
        获取所有分块文本

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, text) 元组列表
        """
        stmt = (
            select(ChunkModel.chunk_id, ChunkModel.text)
            .where(ChunkModel.run_id == run_id)
            .order_by(ChunkModel.chunk_id)
        )
        result = self.session.execute(stmt)
        return [(row.chunk_id, row.text) for row in result.fetchall()]

    def fetch_chunk_styles(self, run_id: str) -> Sequence[Row]:
        return fetch_chunk_styles(self.session, run_id)

    def insert_chunk_style(self, run_id: str, rows: Iterable[ChunkStyleData] | Iterable[Any]) -> None:
        insert_chunk_style(self.session, run_id, rows)

    def insert_chunk_topics(self, run_id: str, rows: Iterable[tuple[int, int, float]]) -> None:
        insert_chunk_topics(self.session, run_id, rows)

    def clear_chunk_topics(self, run_id: str) -> None:
        clear_chunk_topics(self.session, run_id)

    def fetch_chunk_styles_full(self, run_id: str) -> Sequence[Row]:
        return fetch_chunk_styles_full(self.session, run_id)

    def fetch_chunk_imagery_lexicon_densities(self, run_id: str) -> list[tuple[int, float | None]]:
        return fetch_chunk_imagery_lexicon_densities(self.session, run_id)

    def fetch_chunk_topics_agg(self, run_id: str) -> Sequence[Row]:
        """
        获取聚合后的分块主题数据（每个分块的平均主题权重）

        返回 Sequence[Row] 支持字段名访问， 替代元组列表
        """
        return fetch_chunk_topics_agg(self.session, run_id)

    def fetch_chunk_counts(self, run_id: str) -> tuple[int, int]:
        """
        获取分块统计

        Args:
            run_id: 运行ID

        Returns:
            (total_chunks, total_chars) 元组
        """
        stmt = select(
            func.count().label("total_chunks"),
            func.sum(func.length(ChunkModel.text)).label("total_chars"),
        ).where(ChunkModel.run_id == run_id)
        result = self.session.execute(stmt)
        row = result.fetchone()
        if row is None:
            return (0, 0)
        total_chunks = row.total_chunks if row.total_chunks else 0
        total_chars = int(row.total_chars) if row.total_chars else 0
        return (total_chunks, total_chars)

    def fetch_all_chunk_texts(self, run_id: str) -> list[str]:
        """
        获取指定运行的所有分块文本（仅文本）

        新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            文本列表
        """
        stmt = select(ChunkModel.text).where(ChunkModel.run_id == run_id).order_by(ChunkModel.chunk_id)
        result = self.session.execute(stmt)
        return [row.text for row in result.fetchall() if row.text]

    def count_chunks(self, run_id: str) -> int:
        """
        统计指定运行的分块数量

        新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            分块数量
        """
        stmt = select(func.count()).select_from(ChunkModel).where(ChunkModel.run_id == run_id)
        return int(self.session.execute(stmt).scalar_one() or 0)

    def fetch_prev_chunk_text(self, run_id: str, chunk_id: int) -> str | None:
        """
        获取上一个分块的文本

        新增方法支持 rolling_memory.py

        Args:
            run_id: 运行ID
            chunk_id: 当前分块ID

        Returns:
            上一个分块的文本，不存在则返回 None
        """
        if chunk_id <= 0:
            return None
        stmt = select(ChunkModel.text).where(ChunkModel.run_id == run_id, ChunkModel.chunk_id == chunk_id - 1)
        return self.session.execute(stmt).scalar_one_or_none()

    def fetch_next_chunk_text(self, run_id: str, chunk_id: int) -> str | None:
        """
        获取下一个分块的文本

        新增方法支持 rolling_memory.py

        Args:
            run_id: 运行ID
            chunk_id: 当前分块ID

        Returns:
            下一个分块的文本，不存在则返回 None
        """
        stmt = select(ChunkModel.text).where(ChunkModel.run_id == run_id, ChunkModel.chunk_id == chunk_id + 1)
        return self.session.execute(stmt).scalar_one_or_none()

    def has_chunks(self, run_id: str) -> bool:
        """
        检查指定运行是否有分块数据

        新增方法替代 operations.completeness.has_chunks

        Args:
            run_id: 运行ID

        Returns:
            是否有分块数据
        """
        stmt = select(func.count()).select_from(ChunkModel).where(ChunkModel.run_id == run_id)
        count = int(self.session.execute(stmt).scalar_one() or 0)
        return count > 0

    def is_preprocess_complete(self, run_id: str) -> bool:
        """
        检查预处理阶段是否完成

        当当前配置要求语义原文定位时，完成判定不再只看 chunks，
        而是要求 paragraph embedding schema 与数据完整就绪，
        避免半成品 run 被误判为 preprocess 已完成

        RAG 粒度固定为一个自然段：只检查 paragraph embeddings，不再检查 chunk embeddings
        """
        if not self.has_chunks(run_id):
            return False

        if not settings.models.paragraph_embedding.semantic_enabled:
            return True

        expected_dim = settings.models.paragraph_embedding.embedding_dim
        try:
            validate_paragraph_embeddings_schema(self.session, expected_dim)
        except ValueError:
            # 只要当前运行环境要求语义原文定位，而 schema 尚未就绪，就不能跳过 preprocess；
            # 否则会把缺向量的半成品 run 当成完成态，后续直接卡在 readiness
            return False

        if not has_paragraph_embeddings(self.session, run_id):
            return False
        if get_incomplete_paragraph_embedding_chunk_ids(self.session, run_id):
            return False
        return True

    def fetch_chunk_summaries(self, run_id: str) -> Sequence[Row]:
        """
        获取指定运行的所有分块摘要

        返回 Sequence[Row] 支持字段名访问，替代元组列表

        Args:
            run_id: 运行ID

        Returns:
            Row 对象序列，支持字段名访问：row.chunk_id, row.summary
        """
        stmt = (
            select(ChunkSummary.chunk_id, ChunkSummary.summary)
            .where(ChunkSummary.run_id == run_id)
            .order_by(ChunkSummary.chunk_id)
        )
        result = self.session.execute(stmt)
        return result.fetchall()

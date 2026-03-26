"""
创建时间: 2026-03-14
创建者: TraeAI
任务: Repository 基类和 Protocol 接口定义
说明: 实现 ChunkRepository 类，管理文本分块的存储和检索

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 添加查询方法 fetch_chunk_styles_full, fetch_chunk_cultures_full, fetch_chunk_topics_agg, fetch_chunk_counts

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session，使用 ORM 查询替代原生 SQL

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 拆分chunk_repository.py
修改内容: 将 ChunkStyleData 数据类移至 chunk/style_data.py
修改内容: 将 style/culture/topic 操作移至子模块

修改时间: 2026-03-26
修改者: TraeAI
任务: 简化文化指标系统
修改内容: 修复 fetch_chunk_cultures_full 返回类型为 List[Tuple[int, float]]
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple, Union

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.chunking.chunker import Chunk
from src.storage.models import Chunk as ChunkModel
from src.storage.models import ChunkEmbedding
from src.storage.repositories.base import BaseRepository
from src.storage.repositories.chunk import (
    ChunkStyleData,
    clear_chunk_topics,
    fetch_chunk_cultures_full,
    fetch_chunk_styles,
    fetch_chunk_styles_full,
    fetch_chunk_topics_agg,
    insert_chunk_culture,
    insert_chunk_style,
    insert_chunk_topics,
)


class ChunkRepository(BaseRepository["ChunkModel"]):
    """
    分块数据 Repository

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Repository 基类和 Protocol 接口定义
    说明: 管理文本分块的存储和检索，支持 run_id 过滤

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
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

        修改时间: 2026-03-16
        修改者: TraeAI
        修改内容: 插入前先删除该 run_id 的旧数据
        """
        self.session.execute(delete(ChunkModel).where(ChunkModel.run_id == run_id))
        models = [
            ChunkModel(
                chunk_id=chunk.index,
                chapter_id=None,
                text=chunk.text,
                run_id=run_id,
            )
            for chunk in chunks
        ]
        self.session.bulk_save_objects(models)

    def fetch_chunk_texts(self, run_id: str) -> List[Tuple[int, str]]:
        """
        获取所有分块文本

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, text) 元组列表
        """
        stmt = select(ChunkModel.chunk_id, ChunkModel.text).where(ChunkModel.run_id == run_id).order_by(ChunkModel.chunk_id)
        result = self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.fetchall()]

    def fetch_chunk_styles(self, run_id: str) -> List[Tuple[int, float, float, float]]:
        return fetch_chunk_styles(self.session, run_id)

    def insert_chunk_style(self, run_id: str, rows: Union[Iterable[ChunkStyleData], Iterable[Any]]) -> None:
        insert_chunk_style(self.session, run_id, rows)

    def insert_chunk_culture(
        self,
        run_id: str,
        rows: Iterable[Tuple[int, float]],
    ) -> None:
        insert_chunk_culture(self.session, run_id, rows)

    def insert_chunk_topics(self, run_id: str, rows: Iterable[Tuple[int, int, float]]) -> None:
        insert_chunk_topics(self.session, run_id, rows)

    def clear_chunk_topics(self, run_id: str) -> None:
        clear_chunk_topics(self.session, run_id)

    def fetch_chunk_embedding(self, run_id: str, chunk_id: int) -> Optional[bytes]:
        """
        获取分块嵌入向量

        Args:
            run_id: 运行ID
            chunk_id: 分块ID

        Returns:
            嵌入向量字节，不存在则返回 None
        """
        stmt = select(ChunkEmbedding.embedding).where(  # type: ignore[attr-defined]
            ChunkEmbedding.run_id == run_id, ChunkEmbedding.chunk_id == chunk_id
        )
        result = self.session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    def fetch_chunk_styles_full(
        self, run_id: str
    ) -> List[Tuple[int, float, float, float, float, float, float, float, float, float, float, float, float, float, str]]:
        return fetch_chunk_styles_full(self.session, run_id)

    def fetch_chunk_cultures_full(self, run_id: str) -> List[Tuple[int, float]]:
        return fetch_chunk_cultures_full(self.session, run_id)

    def fetch_chunk_topics_agg(self, run_id: str) -> List[Tuple[int, float]]:
        return fetch_chunk_topics_agg(self.session, run_id)

    def fetch_chunk_counts(self, run_id: str) -> Tuple[int, int]:
        """
        获取分块统计

        Args:
            run_id: 运行ID

        Returns:
            (total_chunks, total_chars) 元组
        """
        stmt = select(func.count(), func.sum(func.length(ChunkModel.text))).where(
            ChunkModel.run_id == run_id
        )
        result = self.session.execute(stmt)
        row = result.fetchone()
        if row is None:
            return (0, 0)
        total_chunks = row[0] if row[0] else 0
        total_chars = int(row[1]) if row[1] else 0
        return (total_chunks, total_chars)

    def fetch_all_chunk_texts(self, run_id: str) -> List[str]:
        """
        获取指定运行的所有分块文本（仅文本）

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            文本列表
        """
        stmt = select(ChunkModel.text).where(ChunkModel.run_id == run_id).order_by(ChunkModel.chunk_id)
        result = self.session.execute(stmt)
        return [row[0] for row in result.fetchall() if row[0]]

    def count_chunks(self, run_id: str) -> int:
        """
        统计指定运行的分块数量

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            分块数量
        """
        stmt = select(func.count()).select_from(ChunkModel).where(ChunkModel.run_id == run_id)
        result = self.session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else 0

    def fetch_prev_chunk_text(self, run_id: str, chunk_id: int) -> Optional[str]:
        """
        获取上一个分块的文本

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 rolling_memory.py

        Args:
            run_id: 运行ID
            chunk_id: 当前分块ID

        Returns:
            上一个分块的文本，不存在则返回 None
        """
        if chunk_id <= 0:
            return None
        stmt = select(ChunkModel.text).where(ChunkModel.run_id == run_id, ChunkModel.chunk_id == chunk_id - 1)
        result = self.session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    def fetch_next_chunk_text(self, run_id: str, chunk_id: int) -> Optional[str]:
        """
        获取下一个分块的文本

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 rolling_memory.py

        Args:
            run_id: 运行ID
            chunk_id: 当前分块ID

        Returns:
            下一个分块的文本，不存在则返回 None
        """
        stmt = select(ChunkModel.text).where(ChunkModel.run_id == run_id, ChunkModel.chunk_id == chunk_id + 1)
        result = self.session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    def has_chunks(self, run_id: str) -> bool:
        """
        检查指定运行是否有分块数据

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法替代 operations.completeness.has_chunks

        Args:
            run_id: 运行ID

        Returns:
            是否有分块数据
        """
        stmt = select(func.count()).select_from(ChunkModel).where(ChunkModel.run_id == run_id)
        result = self.session.execute(stmt)
        row = result.fetchone()
        count = row[0] if row else 0
        return count > 0

    def is_preprocess_complete(self, run_id: str) -> bool:
        """
        检查预处理阶段是否完成

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法替代 operations.completeness.is_preprocess_complete

        Args:
            run_id: 运行ID

        Returns:
            预处理是否完成
        """
        return self.has_chunks(run_id)

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
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple, Union, cast

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from src.chunking.chunker import Chunk
from src.storage.models import Chunk as ChunkModel
from src.storage.models import ChunkCulture, ChunkEmbedding, ChunkStyle, ChunkTopic
from src.storage.repositories.base import BaseRepository
from src.storage.repositories.chunk import ChunkStyleData


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
        """
        获取分块风格数据

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, dialogue_ratio, sent_len_std, avg_sent_len) 元组列表
        """
        stmt = select(
            ChunkStyle.chunk_id,
            ChunkStyle.dialogue_ratio,
            ChunkStyle.sent_len_std,
            ChunkStyle.avg_sent_len,
        ).where(ChunkStyle.run_id == run_id)
        result = self.session.execute(stmt)
        return [(row[0], row[1], row[2], row[3]) for row in result.fetchall()]

    def insert_chunk_style(self, run_id: str, rows: Union[Iterable[ChunkStyleData], Iterable[Any]]) -> None:
        """
        插入分块风格数据

        Args:
            run_id: 运行ID
            rows: 风格数据行
        """
        self.session.execute(delete(ChunkStyle).where(ChunkStyle.run_id == run_id))
        style_rows = []
        for row in rows:
            if isinstance(row, ChunkStyleData):
                style_rows.append(row.to_dict(run_id))
            else:
                style_rows.append(cast(dict, row))
        if style_rows:
            self.session.bulk_insert_mappings(ChunkStyle, style_rows)

    def insert_chunk_culture(
        self,
        run_id: str,
        rows: Iterable[Tuple[int, float, float, float, float, float, float]],
    ) -> None:
        """
        插入分块文化数据

        Args:
            run_id: 运行ID
            rows: 文化数据行 (chunk_id, confucian_density, taoist_density, buddhist_density, folk_density, allusion_density, imagery_density)
        """
        self.session.execute(delete(ChunkCulture).where(ChunkCulture.run_id == run_id))
        culture_rows = [
            {
                "chunk_id": row[0],
                "confucian_density": row[1],
                "taoist_density": row[2],
                "buddhist_density": row[3],
                "folk_density": row[4],
                "allusion_density": row[5],
                "imagery_density": row[6],
                "run_id": run_id,
            }
            for row in rows
        ]
        if culture_rows:
            self.session.bulk_insert_mappings(ChunkCulture, culture_rows)

    def insert_chunk_topics(self, run_id: str, rows: Iterable[Tuple[int, int, float]]) -> None:
        """
        插入分块主题数据

        Args:
            run_id: 运行ID
            rows: 主题数据行 (chunk_id, topic_id, topic_weight)
        """
        topic_rows = [
            {
                "chunk_id": row[0],
                "topic_id": row[1],
                "topic_weight": row[2],
                "run_id": run_id,
            }
            for row in rows
        ]
        if topic_rows:
            self.session.bulk_insert_mappings(ChunkTopic, topic_rows)

    def clear_chunk_topics(self, run_id: str) -> None:
        """清空分块主题数据"""
        self.session.execute(delete(ChunkTopic).where(ChunkTopic.run_id == run_id))

    def fetch_chunk_embedding(self, run_id: str, chunk_id: int) -> Optional[bytes]:
        """
        获取分块嵌入向量

        Args:
            run_id: 运行ID
            chunk_id: 分块ID

        Returns:
            嵌入向量字节，不存在则返回 None
        """
        stmt = select(ChunkEmbedding.embedding).where(
            ChunkEmbedding.run_id == run_id, ChunkEmbedding.chunk_id == chunk_id
        )
        result = self.session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    def fetch_chunk_styles_full(
        self, run_id: str
    ) -> List[Tuple[int, float, float, float, float, float, float, float, float, float, float, float, float, float, float, str]]:
        """
        获取完整的分块风格数据

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, mtld, ttr, avg_sent_len, sent_len_std, d_value, pause_density, fight_density, exclaim_density, dialogue_ratio, question_density, sensory_density, metaphor_density, cultural_density, function_word_vector) 元组列表
        """
        stmt = select(
            ChunkStyle.chunk_id,
            ChunkStyle.mtld,
            ChunkStyle.ttr,
            ChunkStyle.avg_sent_len,
            ChunkStyle.sent_len_std,
            ChunkStyle.d_value,
            ChunkStyle.pause_density,
            ChunkStyle.fight_density,
            ChunkStyle.exclaim_density,
            ChunkStyle.dialogue_ratio,
            ChunkStyle.question_density,
            ChunkStyle.sensory_density,
            ChunkStyle.metaphor_density,
            ChunkStyle.cultural_density,
            ChunkStyle.function_word_vector,
        ).where(ChunkStyle.run_id == run_id)
        result = self.session.execute(stmt)
        return [tuple(row) for row in result.fetchall()]

    def fetch_chunk_cultures_full(self, run_id: str) -> List[Tuple[int, float, float, float, float, float]]:
        """
        获取完整的分块文化数据

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, confucian_density, taoist_density, buddhist_density, folk_density, allusion_density) 元组列表
        """
        stmt = select(
            ChunkCulture.chunk_id,
            ChunkCulture.confucian_density,
            ChunkCulture.taoist_density,
            ChunkCulture.buddhist_density,
            ChunkCulture.folk_density,
            ChunkCulture.allusion_density,
        ).where(ChunkCulture.run_id == run_id)
        result = self.session.execute(stmt)
        return [tuple(row) for row in result.fetchall()]

    def fetch_chunk_topics_agg(self, run_id: str) -> List[Tuple[int, float]]:
        """
        获取聚合后的分块主题数据（每个分块的平均主题权重）

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, avg_topic_weight) 元组列表
        """
        stmt = (
            select(ChunkTopic.chunk_id, func.avg(ChunkTopic.topic_weight).label("avg_weight"))
            .where(ChunkTopic.run_id == run_id)
            .group_by(ChunkTopic.chunk_id)
        )
        result = self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.fetchall()]

    def fetch_chunk_counts(self, run_id: str) -> Tuple[int, int]:
        """
        获取分块统计

        Args:
            run_id: 运行ID

        Returns:
            (total_chunks, total_chars) 元组
        """
        stmt = select(func.count(), func.sum(func.length(ChunkModel.text))).where(
            or_(ChunkModel.run_id == run_id, ChunkModel.run_id.is_(None))
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

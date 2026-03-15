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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple, Union, cast

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from src.chunking.chunker import Chunk
from src.storage.models import Chunk as ChunkModel
from src.storage.models import ChunkCulture, ChunkEmbedding, ChunkStyle, ChunkTopic
from src.storage.repositories.base import BaseRepository


@dataclass(frozen=True)
class ChunkStyleData:
    """
    分块风格数据类

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Repository 基类和 Protocol 接口定义
    说明: 封装分块风格指标数据，从 chunk_ops.py 迁移
    """

    chunk_id: int
    mtld: float
    ttr: float
    avg_sent_len: float
    sent_len_std: float
    d_value: float
    pause_density: float
    fight_density: float
    exclaim_density: float
    dialogue_ratio: float
    question_density: float
    sensory_density: float
    metaphor_density: float
    cultural_density: float
    function_word_vector: str
    category_density_combat: float
    category_density_body: float
    category_density_relation: float
    category_density_faction: float
    category_density_command: float
    category_density_action: float
    category_density_psychology: float
    category_density_measure: float
    category_density_emotion: float
    category_density_color: float

    def to_tuple(
        self,
    ) -> Tuple[
        int,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        str,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
    ]:
        return (
            self.chunk_id,
            self.mtld,
            self.ttr,
            self.avg_sent_len,
            self.sent_len_std,
            self.d_value,
            self.pause_density,
            self.fight_density,
            self.exclaim_density,
            self.dialogue_ratio,
            self.question_density,
            self.sensory_density,
            self.metaphor_density,
            self.cultural_density,
            self.function_word_vector,
            self.category_density_combat,
            self.category_density_body,
            self.category_density_relation,
            self.category_density_faction,
            self.category_density_command,
            self.category_density_action,
            self.category_density_psychology,
            self.category_density_measure,
            self.category_density_emotion,
            self.category_density_color,
        )

    def to_dict(self, run_id: str) -> dict:
        """转换为字典格式，用于 bulk_insert_mappings"""
        return {
            "chunk_id": self.chunk_id,
            "mtld": self.mtld,
            "ttr": self.ttr,
            "avg_sent_len": self.avg_sent_len,
            "sent_len_std": self.sent_len_std,
            "d_value": self.d_value,
            "pause_density": self.pause_density,
            "fight_density": self.fight_density,
            "exclaim_density": self.exclaim_density,
            "dialogue_ratio": self.dialogue_ratio,
            "question_density": self.question_density,
            "sensory_density": self.sensory_density,
            "metaphor_density": self.metaphor_density,
            "cultural_density": self.cultural_density,
            "function_word_vector": self.function_word_vector,
            "category_density_combat": self.category_density_combat,
            "category_density_body": self.category_density_body,
            "category_density_relation": self.category_density_relation,
            "category_density_faction": self.category_density_faction,
            "category_density_command": self.category_density_command,
            "category_density_action": self.category_density_action,
            "category_density_psychology": self.category_density_psychology,
            "category_density_measure": self.category_density_measure,
            "category_density_emotion": self.category_density_emotion,
            "category_density_color": self.category_density_color,
            "run_id": run_id,
        }


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

        Args:
            run_id: 运行ID
            chunks: 分块序列
        """
        mappings = [
            {
                "chunk_id": chunk.index,
                "chapter_id": None,
                "char_offset": chunk.start,
                "text": chunk.text,
                "run_id": run_id,
            }
            for chunk in chunks
        ]
        self.session.bulk_insert_mappings(ChunkModel, mappings)  # type: ignore[arg-type]
        self.session.commit()

    def fetch_chunk_texts(self, run_id: str) -> List[Tuple[int, str]]:
        """
        获取指定运行的所有分块文本

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, text) 元组列表
        """
        stmt = select(ChunkModel.chunk_id, ChunkModel.text).where(ChunkModel.run_id == run_id).order_by(ChunkModel.chunk_id)
        result = self.session.execute(stmt)
        return [cast(Tuple[int, str], row) for row in result.fetchall()]

    def fetch_chunk_styles(self, run_id: str) -> List[Tuple[int, float, float, float]]:
        """
        获取指定运行的分块风格数据

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, dialogue_ratio, sent_len_std, avg_sent_len) 元组列表
        """
        stmt = (
            select(ChunkStyle.chunk_id, ChunkStyle.dialogue_ratio, ChunkStyle.sent_len_std, ChunkStyle.avg_sent_len)
            .where(ChunkStyle.run_id == run_id)
            .order_by(ChunkStyle.chunk_id)
        )
        result = self.session.execute(stmt)
        return [cast(Tuple[int, float, float, float], row) for row in result.fetchall()]

    def insert_chunk_style(self, run_id: str, rows: Union[Iterable[ChunkStyleData], Iterable[Any]]) -> None:
        """
        插入分块风格数据

        Args:
            run_id: 运行ID
            rows: 风格数据行，支持 ChunkStyleData 或元组形式
        """
        mappings: List[dict] = []
        for row in rows:
            if isinstance(row, ChunkStyleData):
                mappings.append(row.to_dict(run_id))
            else:
                row_tuple = tuple(row)
                mappings.append(
                    {
                        "chunk_id": row_tuple[0],
                        "mtld": row_tuple[1],
                        "ttr": row_tuple[2],
                        "avg_sent_len": row_tuple[3],
                        "sent_len_std": row_tuple[4],
                        "d_value": row_tuple[5],
                        "pause_density": row_tuple[6],
                        "fight_density": row_tuple[7],
                        "exclaim_density": row_tuple[8],
                        "dialogue_ratio": row_tuple[9],
                        "question_density": row_tuple[10],
                        "sensory_density": row_tuple[11],
                        "metaphor_density": row_tuple[12],
                        "cultural_density": row_tuple[13],
                        "function_word_vector": row_tuple[14],
                        "category_density_combat": row_tuple[15],
                        "category_density_body": row_tuple[16],
                        "category_density_relation": row_tuple[17],
                        "category_density_faction": row_tuple[18],
                        "category_density_command": row_tuple[19],
                        "category_density_action": row_tuple[20],
                        "category_density_psychology": row_tuple[21],
                        "category_density_measure": row_tuple[22],
                        "category_density_emotion": row_tuple[23],
                        "category_density_color": row_tuple[24],
                        "run_id": run_id,
                    }
                )
        self.session.bulk_insert_mappings(ChunkStyle, mappings)  # type: ignore[arg-type]
        self.session.commit()

    def insert_chunk_culture(
        self, run_id: str, rows: Iterable[Tuple[int, float, float, float, float, float, float]]
    ) -> None:
        """
        插入分块文化数据

        Args:
            run_id: 运行ID
            rows: 文化数据行 (chunk_id, confucian_density, taoist_density, buddhist_density, folk_density, allusion_density, imagery_density)
        """
        mappings = [
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
        self.session.bulk_insert_mappings(ChunkCulture, mappings)  # type: ignore[arg-type]
        self.session.commit()

    def insert_chunk_topics(self, run_id: str, rows: Iterable[Tuple[int, int, float]]) -> None:
        """
        插入分块主题数据

        Args:
            run_id: 运行ID
            rows: 主题数据行 (chunk_id, topic_id, topic_weight)
        """
        mappings = [
            {
                "chunk_id": row[0],
                "topic_id": row[1],
                "topic_weight": row[2],
                "run_id": run_id,
            }
            for row in rows
        ]
        self.session.bulk_insert_mappings(ChunkTopic, mappings)  # type: ignore[arg-type]
        self.session.commit()

    def clear_chunk_topics(self, run_id: str) -> None:
        """
        清空指定运行的分块主题数据

        Args:
            run_id: 运行ID
        """
        stmt = delete(ChunkTopic).where(ChunkTopic.run_id == run_id)
        self.session.execute(stmt)
        self.session.commit()

    def fetch_chunk_embedding(self, run_id: str, chunk_id: int) -> Optional[bytes]:
        """
        获取指定分块的嵌入向量

        Args:
            run_id: 运行ID
            chunk_id: 分块ID

        Returns:
            嵌入向量列表，不存在则返回 None
        """
        stmt = select(ChunkEmbedding.embedding_vector).where(
            ChunkEmbedding.run_id == run_id, ChunkEmbedding.chunk_id == chunk_id
        )
        result = self.session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    def fetch_chunk_styles_full(
        self, run_id: str
    ) -> List[Tuple[int, float, float, float, float, float, float, float, float, float, float, float]]:
        """
        获取完整的分块风格数据

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, mtld, ttr, avg_sent_len, d_value, pause_density, fight_density,
             dialogue_ratio, sensory_density, metaphor_density, cultural_density) 元组列表
        """
        stmt = (
            select(
                ChunkStyle.chunk_id,
                ChunkStyle.mtld,
                ChunkStyle.ttr,
                ChunkStyle.avg_sent_len,
                ChunkStyle.d_value,
                ChunkStyle.pause_density,
                ChunkStyle.fight_density,
                ChunkStyle.dialogue_ratio,
                ChunkStyle.sensory_density,
                ChunkStyle.metaphor_density,
                ChunkStyle.cultural_density,
            )
            .where(or_(ChunkStyle.run_id == run_id, ChunkStyle.run_id.is_(None)))
            .order_by(ChunkStyle.chunk_id)
        )
        result = self.session.execute(stmt)
        return [cast(Tuple[int, float, float, float, float, float, float, float, float, float, float, float], row) for row in result.fetchall()]

    def fetch_chunk_cultures_full(self, run_id: str) -> List[Tuple[int, float, float, float, float, float]]:
        """
        获取完整的分块文化数据

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, confucian_density, taoist_density, buddhist_density,
             folk_density, allusion_density) 元组列表
        """
        stmt = (
            select(
                ChunkCulture.chunk_id,
                ChunkCulture.confucian_density,
                ChunkCulture.taoist_density,
                ChunkCulture.buddhist_density,
                ChunkCulture.folk_density,
                ChunkCulture.allusion_density,
            )
            .where(or_(ChunkCulture.run_id == run_id, ChunkCulture.run_id.is_(None)))
            .order_by(ChunkCulture.chunk_id)
        )
        result = self.session.execute(stmt)
        return [cast(Tuple[int, float, float, float, float, float], row) for row in result.fetchall()]

    def fetch_chunk_topics_agg(self, run_id: str) -> List[Tuple[int, float]]:
        """
        获取分块主题聚合数据

        Args:
            run_id: 运行ID

        Returns:
            (topic_id, total_weight) 元组列表，按权重降序排列
        """
        stmt = (
            select(ChunkTopic.topic_id, func.sum(ChunkTopic.topic_weight).label("total_weight"))
            .where(or_(ChunkTopic.run_id == run_id, ChunkTopic.run_id.is_(None)))
            .group_by(ChunkTopic.topic_id)
            .order_by(func.sum(ChunkTopic.topic_weight).desc())
        )
        result = self.session.execute(stmt)
        return [cast(Tuple[int, float], row) for row in result.fetchall()]

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

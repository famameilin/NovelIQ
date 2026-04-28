"""
分块数据协议接口

修复 insert_chunk_culture 参数类型为具名序列

补齐 run_id 参数，并用命名 DTO 替代协议中的裸结构

ChunkStyleData 仅用于类型检查时导入，避免协议模块增加运行时仓储依赖
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sqlalchemy.engine import Row

from src.chunking.chunker import Chunk

from .types import ChunkCounts, ChunkTextRow, ChunkTopicWeight

if TYPE_CHECKING:
    from src.storage.repositories.chunk import ChunkStyleData


@runtime_checkable
class ChunkRepositoryProtocol(Protocol):
    """
    分块数据接口

    管理文本分块的存储和检索
    """

    def insert_chunks(self, run_id: str, chunks: Sequence[Chunk]) -> None:
        """
        批量插入分块数据

        Args:
            chunks: 分块序列
        """
        ...

    def fetch_chunk_texts(self, run_id: str) -> list[ChunkTextRow]:
        """
        获取所有分块文本

        Returns:
            分块文本行列表
        """
        ...

    def fetch_chunk_styles(self, run_id: str) -> Sequence[Row]:
        """
        获取分块风格数据

        Returns:
            Row 对象序列，支持 row.chunk_id / row.dialogue_ratio 等字段名访问
        """
        ...

    def insert_chunk_style(self, run_id: str, rows: Iterable[ChunkStyleData | dict[str, object]]) -> None:
        """
        插入分块风格数据

        Args:
            rows: 风格数据行
        """
        ...

    def insert_chunk_topics(self, run_id: str, rows: Iterable[ChunkTopicWeight]) -> None:
        """
        插入分块主题数据

        Args:
            rows: 主题数据行
        """
        ...

    def clear_chunk_topics(self, run_id: str) -> None:
        """清空分块主题数据"""
        ...

    def fetch_chunk_counts(self, run_id: str) -> ChunkCounts:
        """获取分块数量与字符数统计"""
        ...

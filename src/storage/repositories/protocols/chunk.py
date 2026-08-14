"""
分块数据协议接口

修复 insert_chunk_culture 参数类型为具名序列

补齐 run_id 参数，并用命名 DTO 替代协议中的裸结构

ChunkStyleData 仅用于类型检查时导入，避免协议模块增加运行时仓储依赖
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from src.chunking.chunker import Chunk

from .types import ChunkCounts, ChunkTextRow


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

    def fetch_chunk_counts(self, run_id: str) -> ChunkCounts:
        """获取分块数量与字符数统计"""
        ...

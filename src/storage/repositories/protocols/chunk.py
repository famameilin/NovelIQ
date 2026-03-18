"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
说明: 分块数据协议接口
"""

from __future__ import annotations

from typing import Any, List, Protocol, Sequence, Tuple, runtime_checkable

from src.chunking.chunker import Chunk


@runtime_checkable
class ChunkRepositoryProtocol(Protocol):
    """
    分块数据接口

    管理文本分块的存储和检索。
    """

    def insert_chunks(self, chunks: Sequence[Chunk]) -> None:
        """
        批量插入分块数据

        Args:
            chunks: 分块序列
        """
        ...

    def fetch_chunk_texts(self) -> List[Tuple[int, str]]:
        """
        获取所有分块文本

        Returns:
            (chunk_id, text) 元组列表
        """
        ...

    def fetch_chunk_styles(self) -> List[Tuple[int, float, float, float]]:
        """
        获取分块风格数据

        Returns:
            (chunk_id, dialogue_ratio, sent_len_std, avg_sent_len) 元组列表
        """
        ...

    def insert_chunk_style(self, rows: Sequence[Any]) -> None:
        """
        插入分块风格数据

        Args:
            rows: 风格数据行
        """
        ...

    def insert_chunk_culture(self, rows: Sequence[Tuple[int, float, float, float, float, float, float]]) -> None:
        """
        插入分块文化数据

        Args:
            rows: 文化数据行 (chunk_id, confucian_density, taoist_density, buddhist_density, folk_density, allusion_density, imagery_density)
        """
        ...

    def insert_chunk_topics(self, rows: Sequence[Tuple[int, int, float]]) -> None:
        """
        插入分块主题数据

        Args:
            rows: 主题数据行 (chunk_id, topic_id, topic_weight)
        """
        ...

    def clear_chunk_topics(self) -> None:
        """清空分块主题数据"""
        ...

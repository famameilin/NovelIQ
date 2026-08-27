"""
诊断数据协议接口

用语义 DTO 替代动态字典与裸结构返回值
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import (
    ForeshadowingChunk,
    HighTensionChunk,
    PivotBlock,
    PivotMoment,
    RelationChangeRow,
    RepositoryRecord,
)


@runtime_checkable
class DiagnosisRepositoryProtocol(Protocol):
    """
    诊断数据接口

    管理小说诊断数据的存储和检索
    """

    def get_diagnosis(self, novel_id: str) -> RepositoryRecord:
        """
        获取诊断数据

        Args:
            novel_id: 小说ID

        Returns:
            诊断数据字典
        """
        ...

    def save_diagnosis(self, novel_id: str, diagnosis: RepositoryRecord) -> None:
        """
        保存诊断数据

        Args:
            novel_id: 小说ID
            diagnosis: 诊断数据字典
        """
        ...

    def get_diagnosis_history(self, novel_id: str) -> list[RepositoryRecord]:
        """
        获取诊断历史

        Args:
            novel_id: 小说ID

        Returns:
            诊断历史列表
        """
        ...

    def fetch_pivot_blocks(self, run_id: str, limit: int | None = None) -> list[PivotBlock]:
        """获取转折点分块"""
        ...

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> list[HighTensionChunk]:
        """获取高张力段落（paragraph_curves.surface_tension 排序）"""
        ...

    def fetch_relation_changes(self, run_id: str, limit: int | None = None) -> list[RelationChangeRow]:
        """获取关系变更记录"""
        ...

    def fetch_foreshadowing_chunks(self, run_id: str, limit: int | None = None) -> list[ForeshadowingChunk]:
        """获取伏笔分块"""
        ...

    def fetch_pivot_moments(self, run_id: str, limit: int | None = None) -> list[PivotMoment]:
        """获取高潮时刻"""
        ...

    def fetch_topic_words(self, run_id: str, top_n: int | None = None) -> list[RepositoryRecord]:
        """获取主题词"""
        ...

    def fetch_known_characters(self, run_id: str) -> list[str]:
        """获取数据库图中的已知人物节点"""
        ...

    def fetch_stage_summaries(self, run_id: str) -> list[RepositoryRecord]:
        """获取阶段性摘要"""
        ...

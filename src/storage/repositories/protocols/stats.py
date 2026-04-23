"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
说明: 统计数据协议接口

修改时间: 2026-04-23
任务: P2-基础设施解耦
修改内容: 使用语义 DTO 和 RepositoryRecord，清理协议层动态类型与裸结构暴露。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from sqlalchemy.engine import Row

from .types import (
    ChunkCurveRow,
    CloudAnalysisRecord,
    GlobalContextRecord,
    GlobalStatValue,
    RepositoryRecord,
    RepositoryValue,
    TokenUsageStatsRecord,
)


@runtime_checkable
class StatsRepositoryProtocol(Protocol):
    """
    统计数据接口

    管理小说分析统计数据的存储和检索。
    """

    def get_character_stats(self, novel_id: str) -> list[RepositoryRecord]:
        """
        获取角色统计数据

        Args:
            novel_id: 小说ID

        Returns:
            角色统计列表
        """
        ...

    def get_relation_stats(self, novel_id: str) -> list[RepositoryRecord]:
        """
        获取关系统计数据

        Args:
            novel_id: 小说ID

        Returns:
            关系统计列表
        """
        ...

    def get_dialogue_stats(self, novel_id: str) -> list[RepositoryRecord]:
        """
        获取对话统计数据

        Args:
            novel_id: 小说ID

        Returns:
            对话统计列表
        """
        ...

    def get_summary_stats(self, novel_id: str) -> RepositoryRecord:
        """
        获取摘要统计数据

        Args:
            novel_id: 小说ID

        Returns:
            摘要统计字典
        """
        ...

    def get_graph_data(self, novel_id: str) -> RepositoryRecord:
        """
        获取图表数据

        Args:
            novel_id: 小说ID

        Returns:
            图表数据字典
        """
        ...

    def get_run_metrics(self, run_id: str) -> RepositoryRecord:
        """
        获取运行指标

        Args:
            run_id: 运行ID

        Returns:
            运行指标字典
        """
        ...

    def insert_character_stats(self, novel_id: str, stats: Sequence[RepositoryRecord]) -> None:
        """
        插入角色统计

        Args:
            novel_id: 小说ID
            stats: 统计数据列表
        """
        ...

    def insert_relation_stats(self, novel_id: str, stats: Sequence[RepositoryRecord]) -> None:
        """
        插入关系统计

        Args:
            novel_id: 小说ID
            stats: 统计数据列表
        """
        ...

    def insert_dialogue_stats(self, novel_id: str, stats: Sequence[RepositoryRecord]) -> None:
        """
        插入对话统计

        Args:
            novel_id: 小说ID
            stats: 统计数据列表
        """
        ...

    def insert_summary_stats(self, novel_id: str, stats: RepositoryRecord) -> None:
        """
        插入摘要统计

        Args:
            novel_id: 小说ID
            stats: 统计数据字典
        """
        ...

    def insert_graph_data(self, novel_id: str, graph_data: RepositoryRecord) -> None:
        """
        插入图表数据

        Args:
            novel_id: 小说ID
            graph_data: 图表数据字典
        """
        ...

    def insert_run_metrics(self, run_id: str, metrics: RepositoryRecord) -> None:
        """
        插入运行指标

        Args:
            run_id: 运行ID
            metrics: 指标数据字典
        """
        ...

    def clear_stats(self, novel_id: str) -> None:
        """
        清空统计数据

        Args:
            novel_id: 小说ID
        """
        ...

    def insert_global_stats(self, run_id: str, stats: Iterable[GlobalStatValue]) -> None:
        """插入全局统计数据"""
        ...

    def fetch_global_stats(self, run_id: str) -> list[GlobalStatValue]:
        """获取全局统计数据"""
        ...

    def fetch_global_stats_dict(self, run_id: str) -> dict[str, float]:
        """获取全局统计数据字典"""
        ...

    def insert_chunk_curve(self, run_id: str, rows: Iterable[ChunkCurveRow]) -> None:
        """插入分块曲线数据"""
        ...

    def fetch_token_usage_stats(self, run_id: str, novel_id: str) -> TokenUsageStatsRecord:
        """获取 token 使用统计"""
        ...

    def fetch_cloud_analysis(self, novel_id: str, run_id: str) -> CloudAnalysisRecord | None:
        """获取云端分析结果"""
        ...

    def fetch_global_context(self, run_id: str, novel_id: str) -> GlobalContextRecord | None:
        """获取全局上下文"""
        ...

    def update_global_context(self, run_id: str, novel_id: str, **kwargs: RepositoryValue) -> None:
        """更新全局上下文"""
        ...

    def fetch_chunk_curves_full(self, run_id: str) -> Sequence[Row]:
        """获取分块曲线完整数据"""
        ...

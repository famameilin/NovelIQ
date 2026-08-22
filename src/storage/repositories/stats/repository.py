"""
统计数据 Repository 主类

主Repository类，通过组合方式使用各模块函数

添加 graphs, summaries 模块导入和对应方法
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.models.cloud.schema import CloudAnalysis as CloudAnalysisSchema
from src.storage.repositories.base import BaseRepository

# 导入各模块函数
from . import metrics, runs, summaries


class StatsRepository(BaseRepository[dict[str, Any]]):
    """统计数据 Repository：管理全局统计等数据，按 run_id 隔离；组合 metrics/runs/chunks/summaries 四模块。"""

    # ==================== metrics 模块方法 ====================

    def insert_global_stats(self, run_id: str, stats: Iterable[tuple[str, float | None]]) -> None:
        """插入全局统计数据"""
        return metrics.insert_global_stats(self.session, run_id, stats)

    def fetch_global_stats(self, run_id: str) -> list[tuple[str, float | None]]:
        """获取全局统计数据"""
        return metrics.fetch_global_stats(self.session, run_id)

    def fetch_global_stats_dict(self, run_id: str) -> dict[str, float | None]:
        """获取全局统计数据字典"""
        return metrics.fetch_global_stats_dict(self.session, run_id)

    def insert_token_usage(
        self,
        run_id: str,
        novel_id: str,
        task_type: str,
        call_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None = None,
        chapter_id: int | None = None,
        cache_read_tokens: int | None = None,
        cost: float | None = None,
        accounting_source: str = "reported",
        reasoning_tokens: int | None = None,
        agent_turn_id: int | None = None,
    ) -> int | None:
        """插入 token 使用记录"""
        return metrics.insert_token_usage(
            self.session,
            run_id,
            novel_id,
            task_type,
            call_type,
            model,
            prompt_tokens,
            total_tokens,
            completion_tokens,
            chapter_id,
            cache_read_tokens,
            cost,
            accounting_source,
            reasoning_tokens,
            agent_turn_id,
        )

    def fetch_token_usage_stats(self, run_id: str, novel_id: str) -> dict[str, Any]:
        """获取 token 使用统计"""
        return metrics.fetch_token_usage_stats(self.session, run_id, novel_id)

    # ==================== runs 模块方法 ====================

    def has_aggregated_data(self, run_id: str) -> bool:
        """检查指定运行是否有聚合数据"""
        return runs.has_aggregated_data(self.session, run_id)

    def has_topic_data(self, run_id: str) -> bool:
        """检查指定运行是否有主题数据"""
        return runs.has_topic_data(self.session, run_id)

    def has_diagnosis_data(self, run_id: str) -> bool:
        """检查指定运行是否有诊断数据"""
        return runs.has_diagnosis_data(self.session, run_id)

    def is_aggregate_complete(self, run_id: str) -> bool:
        """检查聚合阶段是否完成"""
        return runs.is_aggregate_complete(self.session, run_id)

    # ==================== metrics 模块补充方法 ====================

    def insert_cloud_analysis(self, run_id: str, analysis: CloudAnalysisSchema) -> None:
        """插入云端分析结果"""
        return metrics.insert_cloud_analysis(self.session, run_id, analysis)

    def fetch_cloud_analysis(self, novel_id: str, run_id: str) -> dict[str, Any] | None:
        """获取云端分析结果"""
        return metrics.fetch_cloud_analysis(self.session, novel_id, run_id)

    def insert_global_context(
        self,
        run_id: str,
        novel_id: str,
        core_characters: str,
        world_setting: str,
        novel_title: str | None = None,
    ) -> None:
        """插入全局上下文"""
        return metrics.insert_global_context(
            self.session, run_id, novel_id, core_characters, world_setting, novel_title
        )

    def fetch_global_context(self, run_id: str, novel_id: str) -> tuple[str, str, str, str] | None:
        """获取全局上下文"""
        return metrics.fetch_global_context(self.session, run_id, novel_id)

    def update_global_context(self, run_id: str, novel_id: str, **kwargs: Any) -> None:
        """更新全局上下文"""
        return metrics.update_global_context(self.session, run_id, novel_id, **kwargs)

    def fetch_novel_title(self, novel_id: str, run_id: str) -> str | None:
        """获取小说标题"""
        return metrics.fetch_novel_title(self.session, novel_id, run_id)

    def has_global_context(self, run_id: str, novel_id: str) -> bool:
        """
        检查是否已存在 global_context 记录

        """
        return metrics.has_global_context(self.session, run_id, novel_id)

    # ==================== summaries 模块方法 ====================

    def insert_chapter_summary(self, run_id: str, chapter_id: int, summary: str, *, commit: bool = True) -> None:
        """插入分块摘要"""
        return summaries.insert_chapter_summary(self.session, run_id, chapter_id, summary, commit=commit)

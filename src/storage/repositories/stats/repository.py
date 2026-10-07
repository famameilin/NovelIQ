"""
统计数据 Repository 主类

主Repository类，通过组合方式使用各模块函数

添加 graphs 模块导入和对应方法
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from src.storage.repositories.base import BaseRepository

# 导入各模块函数
from . import metrics, runs


class StatsRepository(BaseRepository[dict[str, Any]]):
    """统计数据 Repository：管理全局统计等数据，按 run_id 隔离；组合 metrics/runs/chunks/summaries 四模块。"""

    # ==================== metrics 模块方法 ====================

    def insert_global_stats(self, run_id: str, stats: Iterable[tuple[str, float | None]]) -> None:
        """插入全局统计数据"""
        return metrics.insert_global_stats(self.session, run_id, stats)

    def fetch_global_stats_dict(self, run_id: str) -> dict[str, float | None]:
        """获取全局统计数据字典"""
        return metrics.fetch_global_stats_dict(self.session, run_id)

    def insert_model_turn(
        self,
        *,
        run_id: str,
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
        message_key: str | None = None,
    ) -> int:
        """插入非 Agent 模型调用记账行"""
        return metrics.insert_model_turn(
            self.session,
            run_id=run_id,
            task_type=task_type,
            call_type=call_type,
            model=model,
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            completion_tokens=completion_tokens,
            chapter_id=chapter_id,
            cache_read_tokens=cache_read_tokens,
            cost=cost,
            accounting_source=accounting_source,
            reasoning_tokens=reasoning_tokens,
            message_key=message_key,
        )

    # ==================== runs 模块方法 ====================

    def has_topic_data(self, run_id: str) -> bool:
        """检查指定运行是否有主题数据"""
        return runs.has_topic_data(self.session, run_id)

    def has_linguistic_data(self, run_id: str) -> bool:
        """检查指定运行是否有语言结构基础数据"""
        return runs.has_linguistic_data(self.session, run_id)

    # ==================== metrics 模块补充方法 ====================

    def insert_agent_analysis(self, run_id: str, payload: Mapping[str, Any]) -> str:
        """诊断产物追加进分析产物表，返回产物 id"""
        return metrics.insert_agent_analysis(self.session, run_id, payload)

    def fetch_agent_analysis(self, run_id: str) -> dict[str, Any] | None:
        """获取最新诊断产物"""
        return metrics.fetch_agent_analysis(self.session, run_id)

    def fetch_novel_title(self, novel_id: str) -> str | None:
        """获取小说标题"""
        return metrics.fetch_novel_title(self.session, novel_id)

"""
统计数据 Repository 主类

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 拆分stats_repository
说明: 主Repository类，通过组合方式使用各模块函数
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.storage.repositories.base import BaseRepository

# 导入各模块函数
from . import chunks, metrics, runs


class StatsRepository(BaseRepository[Dict[str, Any]]):
    """
    统计数据 Repository

    管理全局统计、情绪曲线、节奏曲线等数据。
    所有方法支持 run_id 参数以区分不同的分析运行。

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 拆分stats_repository
    修改内容: 使用函数组合方式重组代码结构，拆分为3个模块：
        - metrics: 全局统计和Token使用统计
        - runs: 运行状态和完成度检查
        - chunks: 情绪曲线、节奏曲线、文化数据
    """

    # ==================== metrics 模块方法 ====================

    def insert_global_stats(self, run_id: str, stats: Iterable[Tuple[str, float]]) -> None:
        """插入全局统计数据"""
        return metrics.insert_global_stats(self.session, run_id, stats)

    def fetch_global_stats(self, run_id: str) -> List[Tuple[str, float]]:
        """获取全局统计数据"""
        return metrics.fetch_global_stats(self.session, run_id)

    def fetch_global_stats_dict(self, run_id: str) -> Dict[str, float]:
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
        completion_tokens: Optional[int] = None,
        chunk_id: Optional[int] = None,
    ) -> Optional[int]:
        """插入 token 使用记录"""
        return metrics.insert_token_usage(
            self.session, run_id, novel_id, task_type, call_type, model,
            prompt_tokens, total_tokens, completion_tokens, chunk_id
        )

    def fetch_token_usage_stats(self, run_id: str, novel_id: str) -> Dict[str, Any]:
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

    # ==================== chunks 模块方法 ====================

    def insert_emotion_curve(self, run_id: str, rows: Iterable[Tuple[int, float, float, float, float]]) -> None:
        """插入情绪曲线数据"""
        return chunks.insert_emotion_curve(self.session, run_id, rows)

    def insert_rhythm_curve(self, run_id: str, rows: Iterable[Tuple[int, float, float]]) -> None:
        """插入节奏曲线数据"""
        return chunks.insert_rhythm_curve(self.session, run_id, rows)

    def fetch_emotion_curve(self, run_id: str) -> List[Tuple[float, float, float]]:
        """获取情绪曲线数据"""
        return chunks.fetch_emotion_curve(self.session, run_id)

    def fetch_rhythm_curve(self, run_id: str) -> List[Tuple[float]]:
        """获取节奏曲线数据"""
        return chunks.fetch_rhythm_curve(self.session, run_id)

    def fetch_chunk_culture(self, run_id: str) -> List[Tuple[float, float, float, float, float, float]]:
        """获取分块文化数据"""
        return chunks.fetch_chunk_culture(self.session, run_id)

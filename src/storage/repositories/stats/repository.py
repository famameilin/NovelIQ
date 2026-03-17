"""
统计数据 Repository 主类

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 拆分stats_repository
说明: 主Repository类，通过组合方式使用各模块函数

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 补充遗漏方法
修改内容: 添加 graphs, summaries 模块导入和对应方法
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.models.cloud.schema import CloudAnalysis as CloudAnalysisSchema
from src.storage.repositories.base import BaseRepository

# 导入各模块函数
from . import chunks, graphs, metrics, runs, summaries


class StatsRepository(BaseRepository[Dict[str, Any]]):
    """
    统计数据 Repository

    管理全局统计、情绪曲线、节奏曲线等数据。
    所有方法支持 run_id 参数以区分不同的分析运行。

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 拆分stats_repository
    修改内容: 使用函数组合方式重组代码结构，拆分为5个模块：
        - metrics: 全局统计和Token使用统计、云端分析、全局上下文
        - runs: 运行状态和完成度检查
        - chunks: 情绪曲线、节奏曲线、文化数据
        - summaries: 分块摘要、角色出场信息
        - graphs: 图数据存储
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

    def fetch_emotion_curve_full(self, run_id: str) -> List[Tuple[int, float, float, float, float]]:
        """获取情绪曲线完整数据（包含 chunk_id）"""
        return chunks.fetch_emotion_curve_full(self.session, run_id)

    def fetch_rhythm_curve_full(self, run_id: str) -> List[Tuple[int, float, float]]:
        """获取节奏曲线完整数据（包含 chunk_id）"""
        return chunks.fetch_rhythm_curve_full(self.session, run_id)

    def fetch_emotion_densities(self, run_id: str) -> List[Tuple[float, float]]:
        """获取情绪密度数据"""
        return chunks.fetch_emotion_densities(self.session, run_id)

    # ==================== metrics 模块补充方法 ====================

    def insert_cloud_analysis(self, run_id: str, analysis: CloudAnalysisSchema) -> None:
        """插入云端分析结果"""
        return metrics.insert_cloud_analysis(self.session, run_id, analysis)

    def fetch_cloud_analysis(self, novel_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        """获取云端分析结果"""
        return metrics.fetch_cloud_analysis(self.session, novel_id, run_id)

    def insert_global_context(
        self,
        run_id: str,
        novel_id: str,
        core_characters: str,
        world_setting: str,
        novel_title: Optional[str] = None,
    ) -> None:
        """插入全局上下文"""
        return metrics.insert_global_context(
            self.session, run_id, novel_id, core_characters, world_setting, novel_title
        )

    def fetch_global_context(self, run_id: str, novel_id: str) -> Optional[Tuple[str, str, str, str]]:
        """获取全局上下文"""
        return metrics.fetch_global_context(self.session, run_id, novel_id)

    def update_global_context(self, run_id: str, novel_id: str, **kwargs: Any) -> None:
        """更新全局上下文"""
        return metrics.update_global_context(self.session, run_id, novel_id, **kwargs)

    def fetch_novel_title(self, novel_id: str, run_id: str) -> Optional[str]:
        """获取小说标题"""
        return metrics.fetch_novel_title(self.session, novel_id, run_id)

    # ==================== summaries 模块方法 ====================

    def insert_chunk_summary(self, run_id: str, chunk_id: int, summary: str) -> None:
        """插入分块摘要"""
        return summaries.insert_chunk_summary(self.session, run_id, chunk_id, summary)

    def insert_character_appearances(self, run_id: str, chunk_id: int, appearances: Sequence[Any]) -> None:
        """插入角色出场信息"""
        return summaries.insert_character_appearances(self.session, run_id, chunk_id, appearances)

    # ==================== graphs 模块方法 ====================

    def save_graph(self, run_id: str, graph_name: str, graph_json: str) -> None:
        """保存图数据到数据库"""
        return graphs.save_graph(self.session, run_id, graph_name, graph_json)

    def load_graph(self, run_id: str, graph_name: str) -> Optional[str]:
        """从数据库加载图数据"""
        return graphs.load_graph(self.session, run_id, graph_name)

"""
统计数据 Repository 模块

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 拆分stats_repository
说明: 保持向后兼容的导入接口

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 补充遗漏方法
修改内容: 添加 graphs, summaries 模块导出
"""

from __future__ import annotations

from .chunks import (
    fetch_chunk_culture,
    fetch_chunk_curves_full,
    fetch_emotion_densities,
    insert_chunk_curve,
)
from .metrics import (
    fetch_cloud_analysis,
    fetch_global_context,
    fetch_global_stats,
    fetch_global_stats_dict,
    fetch_novel_title,
    fetch_token_usage_stats,
    insert_cloud_analysis,
    insert_global_context,
    insert_global_stats,
    insert_token_usage,
    update_global_context,
)
from .repository import StatsRepository
from .runs import (
    has_aggregated_data,
    has_diagnosis_data,
    has_topic_data,
    is_aggregate_complete,
)
from .summaries import (
    fetch_chunk_summaries_by_range,
    insert_character_appearances,
    insert_chunk_summary,
    insert_stage_summary,
)

__all__ = [
    "StatsRepository",
    # metrics
    "insert_global_stats",
    "fetch_global_stats",
    "fetch_global_stats_dict",
    "insert_token_usage",
    "fetch_token_usage_stats",
    "insert_cloud_analysis",
    "fetch_cloud_analysis",
    "insert_global_context",
    "fetch_global_context",
    "update_global_context",
    "fetch_novel_title",
    # runs
    "has_aggregated_data",
    "has_topic_data",
    "has_diagnosis_data",
    "is_aggregate_complete",
    # chunks
    "insert_chunk_curve",
    "fetch_chunk_culture",
    "fetch_chunk_curves_full",
    "fetch_emotion_densities",
    # summaries
    "insert_chunk_summary",
    "insert_character_appearances",
    "insert_stage_summary",
    "fetch_chunk_summaries_by_range",
]

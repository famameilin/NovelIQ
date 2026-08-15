"""
统计数据 Repository 模块

保持向后兼容的导入接口

添加 graphs, summaries 模块导出
"""

from __future__ import annotations

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
    fetch_chapter_summaries_by_range,
    insert_chapter_summary,
    insert_stage_summary,
)

__all__ = [
    "StatsRepository",
    # 指标仓储
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
    # run 相关仓储
    "has_aggregated_data",
    "has_topic_data",
    "has_diagnosis_data",
    "is_aggregate_complete",
    # 汇总仓储
    "insert_chapter_summary",
    "insert_stage_summary",
    "fetch_chapter_summaries_by_range",
]

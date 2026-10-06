"""
统计数据 Repository 模块

导出当前统计仓储及实际运行数据查询
"""

from __future__ import annotations

from .metrics import (
    fetch_cloud_analysis,
    fetch_global_stats_dict,
    fetch_novel_title,
    fetch_token_usage_stats,
    insert_cloud_analysis,
    insert_global_stats,
    insert_model_turn,
)
from .repository import StatsRepository
from .runs import (
    has_diagnosis_data,
    has_linguistic_data,
    has_topic_data,
    is_aggregate_complete,
)

__all__ = [
    "StatsRepository",
    # 指标仓储
    "insert_global_stats",
    "fetch_global_stats_dict",
    "insert_model_turn",
    "fetch_token_usage_stats",
    "insert_cloud_analysis",
    "fetch_cloud_analysis",
    "fetch_novel_title",
    # run 相关仓储
    "has_linguistic_data",
    "has_topic_data",
    "has_diagnosis_data",
    "is_aggregate_complete",
]

"""
统计数据 Repository 模块

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 拆分stats_repository
说明: 保持向后兼容的导入接口
"""

from __future__ import annotations

from .chunks import (
    fetch_chunk_culture,
    fetch_emotion_curve,
    fetch_rhythm_curve,
    insert_emotion_curve,
    insert_rhythm_curve,
)
from .metrics import (
    fetch_global_stats,
    fetch_global_stats_dict,
    fetch_token_usage_stats,
    insert_global_stats,
    insert_token_usage,
)
from .repository import StatsRepository
from .runs import (
    has_aggregated_data,
    has_diagnosis_data,
    has_topic_data,
    is_aggregate_complete,
)

__all__ = [
    "StatsRepository",
    # metrics
    "insert_global_stats",
    "fetch_global_stats",
    "fetch_global_stats_dict",
    "insert_token_usage",
    "fetch_token_usage_stats",
    # runs
    "has_aggregated_data",
    "has_topic_data",
    "has_diagnosis_data",
    "is_aggregate_complete",
    # chunks
    "insert_emotion_curve",
    "insert_rhythm_curve",
    "fetch_emotion_curve",
    "fetch_rhythm_curve",
    "fetch_chunk_culture",
]

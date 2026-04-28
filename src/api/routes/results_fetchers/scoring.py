"""
评分计算兼容转发层。

说明: 旧 route helper 文件路径仍保留，但实际实现已经收口到 services.results_queries。
"""

from src.api.services.results_queries.common import (
    _calculate_narrative_focus_scores,
    _normalize_arc_scores,
)

__all__ = ["_calculate_narrative_focus_scores", "_normalize_arc_scores"]

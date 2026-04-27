"""
评分计算兼容转发层。

创建时间: 2026-03-28
创建者: TraeAI
任务: consolidate-codebase-architecture
说明: 旧 route helper 文件路径仍保留，但实际实现已经收口到 services.results_queries。

修改时间: 2026-04-27
修改者: Codex
任务: protagonist-focus-contract
修改内容: 将旧单主角评分入口替换为新的焦点合同评分入口，避免旧命名继续承载活跃语义。
"""

from src.api.services.results_queries.common import (
    _calculate_narrative_focus_scores,
    _normalize_arc_scores,
)

__all__ = ["_calculate_narrative_focus_scores", "_normalize_arc_scores"]

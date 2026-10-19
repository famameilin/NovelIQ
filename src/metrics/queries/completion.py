"""所属领域的产物完整性查询，供恢复编排调用

聚合完成由 runs.aggregate_completed_at 表达（不靠某一统计列非空，
avg_mtld 允许已算但为 NULL）。
"""

from __future__ import annotations

from src.storage import Storage


def is_aggregate_complete(session: Storage, run_id: str) -> bool:
    """检查聚合阶段是否完成（章节存在且正式聚合完成事实非空）。Args: session/run_id；Returns: 是否完成。"""
    chapters_count = session.reads.metrics_queries_completion_is_aggregate_complete_2(run_id) or 0
    aggregate_completed_at = session.reads.metrics_queries_completion_is_aggregate_complete_1(run_id)
    return chapters_count > 0 and aggregate_completed_at is not None

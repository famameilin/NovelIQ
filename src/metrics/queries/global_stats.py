"""全书充分统计量的计算与保存入口

16 个具名结果按运行写入 analysis_runs 的明确列（分子/分母不落库，密度与张力读投影计算）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session


def save_global_stats(session: Session, run_id: str) -> list[tuple[str, float | None]]:
    """统计模块计算并保存自己负责的全书充分统计量（写入 analysis_runs 具名列）"""
    from src.storage.repositories import StatsRepository

    values = query_global_stats(session, run_id)
    StatsRepository(session).insert_global_stats(run_id, values)
    return values


def query_global_stats(session: Session, run_id: str) -> list[tuple[str, float | None]]:
    """读取本运行的充分统计量，再交给纯计算函数"""
    from src.metrics.curve_metrics import compute_global_stats
    from src.storage.repositories.metric_inputs import fetch_global_stat_rows

    return compute_global_stats(fetch_global_stat_rows(session, run_id))

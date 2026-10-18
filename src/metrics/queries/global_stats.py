"""全书充分统计量的计算与保存入口

2026-10-16 全库 3NF 改造：独立 global_stats 表退场，16 个具名结果按运行写入
analysis_runs 的明确列（分子/分母不落库，密度与张力读投影计算）。
"""

from __future__ import annotations

from src.storage import Storage


def save_global_stats(session: Storage, run_id: str) -> list[tuple[str, float | None]]:
    """统计模块计算并保存自己负责的全书充分统计量（写入 analysis_runs 具名列）"""
    pass

    values = query_global_stats(session, run_id)
    session.statistics.insert_global_stats(run_id, values)
    return values


def query_global_stats(session: Storage, run_id: str) -> list[tuple[str, float | None]]:
    """读取本运行的充分统计量，再交给纯计算函数"""
    from src.metrics.curve_metrics import compute_global_stats

    pass

    return compute_global_stats(session.paragraphs.fetch_global_stat_rows(run_id))

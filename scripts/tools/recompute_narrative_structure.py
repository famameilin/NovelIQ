"""
单独复算某个 run 的三幕结构诊断信息

不重跑整本分析，直接从已落库的 annotation/chunk_curves 现算三幕比例，
便于核对主高潮区、代表峰和第一幕结束边界。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.metrics.aggregate.computers import _align_narrative_structure_inputs  # noqa: E402
from src.metrics.queries.fetchers import fetch_annotation_data, fetch_tension_data  # noqa: E402
from src.metrics.narrative_metrics import ThreeActStructureDiagnostics, analyze_three_act_structure  # noqa: E402
from src.storage.db import get_session_factory  # noqa: E402
from src.storage.repositories import AnnotationRepository, RunRepository, StatsRepository  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """
    解析复算脚本命令行参数。
    """
    parser = argparse.ArgumentParser(description="单独复算某个 run 的三幕结构")
    parser.add_argument("run_id", help="分析任务 run_id")
    return parser


def _build_aligned_three_act_diagnostics(
    annotation_data,
    tension_data,
) -> ThreeActStructureDiagnostics | None:
    """
    复算脚本必须复用聚合主链的 chunk_id 对齐与空张力过滤逻辑，
    避免脚本结果与 narrative-structure 接口口径分叉，或因 NULL tension 直接报错。
    """
    aligned_inputs = _align_narrative_structure_inputs(annotation_data, tension_data)
    if not aligned_inputs.chapter_ids or len(aligned_inputs.positions) < 2:
        return None
    return analyze_three_act_structure(
        aligned_inputs.positions,
        aligned_inputs.event_types,
        aligned_inputs.cliffhangers,
        aligned_inputs.pivot_moments,
        aligned_inputs.tension_scores,
    )


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()

    session = get_session_factory()()
    try:
        run_repo = RunRepository(session)
        run_record = run_repo.get_run(args.run_id)
        if run_record is None:
            print(f"错误: run_id={args.run_id} 在当前数据库中不存在", file=sys.stderr)
            return 1

        annotation_repo = AnnotationRepository(session)
        stats_repo = StatsRepository(session)
        annotation_data = fetch_annotation_data(annotation_repo, args.run_id)
        tension_data = fetch_tension_data(stats_repo, args.run_id)
        if not annotation_data.chapter_ids or not tension_data.chapter_ids:
            print(
                f"错误: run_id={args.run_id} 缺少 annotation 或 chunk_curves 数据，无法复算三幕结构",
                file=sys.stderr,
            )
            return 1
        diagnostics = _build_aligned_three_act_diagnostics(annotation_data, tension_data)
        if diagnostics is None:
            print(
                (
                    f"错误: run_id={args.run_id} annotation 与 chunk_curves "
                    "没有可对齐的有效 tension 数据，无法复算三幕结构"
                ),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(diagnostics.to_dict(), ensure_ascii=False, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

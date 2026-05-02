"""
单独复算某个 run 的三幕结构诊断信息

创建时间: 2026-05-02
任务: three-act-structure-v2
说明: 不重跑整本分析，直接从已落库的 annotation/chunk_curves 现算三幕比例，
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

from src.metrics.aggregate.fetchers import fetch_annotation_data, fetch_tension_data  # noqa: E402
from src.metrics.narrative_metrics import analyze_three_act_structure  # noqa: E402
from src.storage.db import get_session_factory  # noqa: E402
from src.storage.repositories import AnnotationRepository, StatsRepository  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="单独复算某个 run 的三幕结构")
    parser.add_argument("run_id", help="分析任务 run_id")
    return parser


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()

    session = get_session_factory()()
    try:
        annotation_repo = AnnotationRepository(session)
        stats_repo = StatsRepository(session)
        annotation_data = fetch_annotation_data(annotation_repo, args.run_id)
        tension_data = fetch_tension_data(stats_repo, args.run_id)
        diagnostics = analyze_three_act_structure(
            annotation_data.event_types,
            annotation_data.cliffhangers,
            annotation_data.pivot_moments,
            tension_data.tension_composite_scores,
        )
        print(json.dumps(diagnostics.to_dict(), ensure_ascii=False, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

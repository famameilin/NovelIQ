from __future__ import annotations

from src.cli.commands import (
    EVENT_TYPE_SCORES,
    build_cloud_payload,
    run_aggregate,
    run_annotate,
    run_cloud_diagnose,
    run_diagnose,
    run_preprocess,
    run_topic_model,
)
from src.cli.parser import build_parser, main
from src.cli.workflow import StageResult, run_full_workflow

__all__ = [
    "EVENT_TYPE_SCORES",
    "StageResult",
    "build_cloud_payload",
    "build_parser",
    "main",
    "run_aggregate",
    "run_annotate",
    "run_cloud_diagnose",
    "run_diagnose",
    "run_full_workflow",
    "run_preprocess",
    "run_topic_model",
]

if __name__ == "__main__":
    raise SystemExit(main())

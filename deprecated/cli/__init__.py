"""
创建时间: 2025-03-11
创建者: TraeAI
任务: CLI模块入口

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 项目文件结构整理与拆解 - 保持原有导入结构
"""

from src.cli.main import (
    EVENT_TYPE_SCORES,
    StageResult,
    build_cloud_payload,
    build_parser,
    main,
    run_aggregate,
    run_annotate,
    run_cloud_diagnose,
    run_diagnose,
    run_full_workflow,
    run_preprocess,
)

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
]

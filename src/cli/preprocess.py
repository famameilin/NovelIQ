"""
预处理命令行入口

创建时间: 2025-03-11
创建者: TraeAI
任务: 预处理流程
修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-module-coupling
修改内容: 重构为 CLI 薄层，核心业务逻辑委托给 src.workflows 模块
"""

from __future__ import annotations

from src.workflows.curve_metrics import (
    EVENT_TYPE_SCORES,
    compute_emotion_curve,
    compute_global_stats,
    compute_rhythm_curve,
    compute_tension_signals,
    load_all_lexicons,
)
from src.workflows.preprocess import run_preprocess

__all__ = [
    "EVENT_TYPE_SCORES",
    "compute_emotion_curve",
    "compute_global_stats",
    "compute_rhythm_curve",
    "compute_tension_signals",
    "load_all_lexicons",
    "run_preprocess",
]

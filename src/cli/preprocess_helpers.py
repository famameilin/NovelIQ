"""
预处理辅助函数模块 - 兼容层

创建时间: 2026-03-13
创建者: TraeAI
任务: refactor-analysis-layer-functions
说明: 从 run_preprocess 函数中提取的辅助函数，实现职责分离

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-module-coupling-phase2
修改内容: 将本文件改为兼容层，重新导出 workflows.preprocess_helpers 的内容
          原实现已迁移到 src.workflows.preprocess_helpers

此文件保留向后兼容，所有实现已迁移到 src.workflows.preprocess_helpers
"""

from src.workflows.preprocess_helpers import (
    _compute_chunk_culture_metrics,
    _compute_chunk_style_metrics,
    _load_all_lexicons_for_preprocess,
)

__all__ = [
    "_load_all_lexicons_for_preprocess",
    "_compute_chunk_style_metrics",
    "_compute_chunk_culture_metrics",
]

"""
诊断命令行入口

创建时间: 2026-03-14
创建者: TraeAI
任务: refactor-module-coupling
说明: 此文件为 CLI 薄层，核心业务逻辑委托给 src.workflows 模块
"""

from __future__ import annotations

from src.workflows.diagnose import (
    build_cloud_payload,
    run_cloud_diagnose,
    run_diagnose,
    run_local_diagnose,
)

__all__ = [
    "build_cloud_payload",
    "run_cloud_diagnose",
    "run_diagnose",
    "run_local_diagnose",
]

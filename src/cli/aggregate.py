"""
聚合命令行入口

创建时间: 2026-03-14
创建者: TraeAI
任务: refactor-module-coupling
说明: 此文件为 CLI 薄层，核心业务逻辑委托给 src.workflows 模块
"""

from __future__ import annotations

from src.workflows.aggregate import run_aggregate

__all__ = [
    "run_aggregate",
]

"""
主题建模命令行入口

创建时间: 2026-03-14
创建者: TraeAI
任务: refactor-module-coupling
说明: 此文件为 CLI 薄层，核心业务逻辑委托给 src.workflows 模块
修改时间: 2026-03-14
修改者: TraeAI
修改内容: 重构为薄层，将核心业务逻辑委托给 src.workflows.topic 模块
"""

from __future__ import annotations

from src.workflows.topic import run_topic_model

__all__ = [
    "run_topic_model",
]

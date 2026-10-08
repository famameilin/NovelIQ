"""
API 异常与错误映射

说明: 小说文本导入自身的输入异常（文件类型/文件存储）由 api 定义；运行与编排异常
      归 workflows，事实图与配置异常归各自域。API 中间件据此映射 HTTP 状态码。
"""

from __future__ import annotations

from src.config.exceptions import SettingsValidationError
from src.fact_graph.errors import GraphReadinessError
from src.workflows.exceptions import (
    AnalysisError,
    AnalysisNotCompleteError,
    NovelNotFoundError,
)

__all__ = [
    "AnalysisError",
    "AnalysisNotCompleteError",
    "GraphReadinessError",
    "NovelNotFoundError",
    "SettingsValidationError",
]

"""
API 异常与错误映射

说明: 小说文本导入自身的输入异常（文件类型/文件存储）由 api 定义；运行与编排异常
      归 workflows，事实图与配置异常归各自域。API 中间件据此映射 HTTP 状态码。
"""

from __future__ import annotations

from src.config.exceptions import SettingsValidationError
from src.utils.exceptions import GraphReadinessError
from src.workflows.exceptions import (
    AnalysisError,
    AnalysisNotCompleteError,
    NovelNotFoundError,
)


class InvalidFileError(Exception):
    """文本导入前的文件校验失败（如非 .txt）"""

    def __init__(self, filename: str | None = None, message: str | None = None):
        self.filename = filename
        self.message = message or (f"Invalid file: {filename}" if filename else "Invalid file")
        super().__init__(self.message)


class FileStorageError(Exception):
    """上传文件落盘失败"""

    def __init__(self, filename: str | None = None, message: str | None = None):
        self.filename = filename
        self.message = message or (f"File storage error: {filename}" if filename else "File storage error")
        super().__init__(self.message)


__all__ = [
    "AnalysisError",
    "AnalysisNotCompleteError",
    "FileStorageError",
    "GraphReadinessError",
    "InvalidFileError",
    "NovelNotFoundError",
    "SettingsValidationError",
]

from __future__ import annotations

from src.api.exceptions import (
    AnalysisError,
    AnalysisNotCompleteError,
    FileStorageError,
    InvalidFileError,
    NovelNotFoundError,
)
from src.api.middleware import register_exception_handlers

__all__ = [
    "app",
    "NovelNotFoundError",
    "InvalidFileError",
    "AnalysisNotCompleteError",
    "AnalysisError",
    "FileStorageError",
    "register_exception_handlers",
]


def __getattr__(name: str):
    """
    延迟导入 app，避免 python -m src.api.main 时的 RuntimeWarning

    说明: 当使用 python -m 运行 main.py 时，__init__.py 会先被导入，
          如果直接导入 app 会导致 main 模块在 sys.modules 中但未执行 __main__
    """
    if name == "app":
        from src.api.main import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

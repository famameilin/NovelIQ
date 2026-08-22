from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

_active_file_handlers: dict[str, int] = {}


class AnalysisLogger:
    """
    分析日志记录器
    """

    def __init__(self, log_base_dir: Path, task_id: str):
        self._task_id = task_id
        self._log_dir = log_base_dir / task_id
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._handler_id: int | None = None
        self._setup_file_loggers()

    def _setup_file_loggers(self) -> None:
        global _active_file_handlers
        log_file = self._log_dir / "analysis.log"
        log_key = str(log_file)
        if log_key in _active_file_handlers:
            try:
                logger.remove(_active_file_handlers[log_key])
            except ValueError:
                pass
        self._handler_id = logger.add(
            str(log_file),
            level="DEBUG",
            rotation="10 MB",
            retention="30 days",
            encoding="utf-8",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        )
        _active_file_handlers[log_key] = self._handler_id

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    def write_summary(self, summary: dict[str, Any]) -> None:
        summary_file = self._log_dir / "summary.json"
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self) -> None:
        global _active_file_handlers
        if self._handler_id is not None:
            try:
                logger.remove(self._handler_id)
                log_key = str(self._log_dir / "analysis.log")
                if log_key in _active_file_handlers:
                    del _active_file_handlers[log_key]
            except ValueError:
                pass

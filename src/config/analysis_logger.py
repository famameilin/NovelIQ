from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

_active_file_handlers: dict[str, int] = {}


class AnalysisLogger:
    """
    分析日志记录器

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 分析流程日志记录

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 合并本地和云端日志为统一的 prompts.jsonl
    修改内容: 移除 local_prompts.jsonl 和 cloud_prompts.jsonl 的区分，统一使用 prompts.jsonl
    """

    def __init__(self, log_base_dir: Path, task_id: str):
        self._task_id = task_id
        self._log_dir = log_base_dir / task_id
        self._log_dir.mkdir(parents=True, exist_ok=True)
        # 统一的 prompt 日志文件
        self._prompts_file = self._log_dir / "prompts.jsonl"
        self._annotation_file = self._log_dir / "annotations.jsonl"
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

    def log_prompt(
        self,
        messages: list[dict[str, str]],
        response: str,
        metadata: dict[str, Any] | None = None,
        chunk_id: int | None = None,
    ) -> None:
        """
        记录统一的 prompt/response 日志

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: 合并本地和云端日志
        说明: 统一的日志记录方法，不再区分本地和云端
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "chunk_id": chunk_id,
            "messages": messages,
            "response": response,
            "metadata": metadata or {},
        }
        self._append_jsonl(self._prompts_file, entry)

    def log_annotation(
        self,
        chunk_id: int,
        annotation: dict[str, Any],
        raw_response: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "chunk_id": chunk_id,
            "annotation": annotation,
            "raw_response": raw_response,
            "metadata": metadata or {},
        }
        self._append_jsonl(self._annotation_file, entry)

    def _append_jsonl(self, file_path: Path, entry: dict[str, Any]) -> None:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

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


def get_or_create_analysis_logger(
    log_base_dir: Path,
    task_id: str,
) -> AnalysisLogger:
    return AnalysisLogger(log_base_dir, task_id)

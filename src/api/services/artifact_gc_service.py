"""
任务与小说产物清理服务

说明: 将 NovelService 中的文件系统清理逻辑拆到独立服务，避免领域服务混入 logs/outputs/source file 的 GC 细节
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from loguru import logger

from src.storage.path_resolver import resolve_run_model_dir


class ArtifactGcService:
    """
    文件产物清理服务
    """

    def __init__(self, logs_dir: Path, outputs_dir: Path) -> None:
        """
        初始化产物清理服务
        """
        self.logs_dir = logs_dir
        self.outputs_dir = outputs_dir

    def delete_novel_source_file(self, file_path: str | None) -> None:
        """
        删除小说源文件
        """
        if not file_path:
            return

        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Novel source file deleted: {file_path}")

    def delete_task_artifacts(self, task_id: str, run_id: str) -> None:
        """2026-08-30 用于删除任务日志导出文件与 run 私有模型目录"""
        word2vec_model_dir = resolve_run_model_dir(run_id, "word2vec")
        output_file = self.outputs_dir / f"{task_id}.json"
        if output_file.exists():
            output_file.unlink()
            logger.info(f"Deleted task output file: {output_file}")

        candidate_log_dirs = [self.logs_dir / run_id]
        if run_id != task_id:
            candidate_log_dirs.append(self.logs_dir / task_id)

        for log_dir in candidate_log_dirs:
            if log_dir.exists():
                shutil.rmtree(log_dir)
                logger.info(f"Deleted task log directory: {log_dir}")

        if word2vec_model_dir.exists():
            shutil.rmtree(word2vec_model_dir)
            logger.info(f"Deleted task Word2Vec model directory: {word2vec_model_dir}")

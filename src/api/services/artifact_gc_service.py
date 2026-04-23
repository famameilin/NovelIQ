"""
任务与小说产物清理服务。

创建时间: 2026-04-23
任务: p2-artifact-gc-service
说明: 将 NovelService 中的文件系统清理逻辑拆到独立服务，避免领域服务混入 logs/outputs/source file 的 GC 细节。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from loguru import logger


class ArtifactGcService:
    """
    文件产物清理服务。

    创建时间: 2026-04-23
    任务: p2-artifact-gc-service
    新建原因: 把 task/novel 删除中的文件系统职责从 NovelService 中拆离。
    """

    def __init__(self, logs_dir: Path, outputs_dir: Path) -> None:
        """
        初始化产物清理服务。

        创建时间: 2026-04-23
        任务: p2-artifact-gc-service
        新建原因: 固定 logs/outputs 根目录，避免调用方重复拼路径。
        """
        self.logs_dir = logs_dir
        self.outputs_dir = outputs_dir

    def delete_novel_source_file(self, file_path: str | None) -> None:
        """
        删除小说源文件。

        创建时间: 2026-04-23
        任务: p2-artifact-gc-service
        新建原因: 将源文件删除从 NovelService 拆出，统一纳入 artifact GC 服务管理。
        """
        if not file_path:
            return

        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Novel source file deleted: {file_path}")

    def delete_task_artifacts(self, task_id: str, run_id: str) -> None:
        """
        删除任务对应的日志与导出文件。

        创建时间: 2026-04-23
        任务: p2-artifact-gc-service
        新建原因: 将 task 文件产物删除从 NovelService 拆出，避免领域服务直接操纵文件系统。
        """
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

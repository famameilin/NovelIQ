"""
任务管理器模块

创建时间: 2025-03-11
创建者: TraeAI
任务: 任务管理

修改时间: 2026-03-19
修改者: TraeAI
任务: ID系统统一优化
修改内容: 确认统一使用task_id作为对外接口和内部存储标识

说明: TaskManager统一使用task_id（8位短ID）作为任务标识，
      不涉及run_id（36位UUID）的转换，转换逻辑由调用方处理。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any
from loguru import logger

from src.api.models.responses import TaskStatus


@dataclass
class TaskInfo:
    task_id: str
    novel_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    stage: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Any = None


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, TaskInfo] = {}

    def create_task(self, task_id: str, novel_id: str) -> TaskInfo:
        task = TaskInfo(task_id=task_id, novel_id=novel_id, status=TaskStatus.PENDING, started_at=datetime.now())
        self._tasks[task_id] = task
        logger.info(f"Task created: {task_id} for novel {novel_id}")
        return task

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        return self._tasks.get(task_id)

    def get_tasks_by_novel(self, novel_id: str) -> list[TaskInfo]:
        return [t for t in self._tasks.values() if t.novel_id == novel_id]

    def update_task(self, task_id: str, **kwargs) -> None:
        if task_id in self._tasks:
            task = self._tasks[task_id]
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            logger.debug(f"Task updated: {task_id} - {kwargs}")

    def complete_task(self, task_id: str, success: bool = True, error: Optional[str] = None) -> None:
        if task_id not in self._tasks:
            return

        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED if success else TaskStatus.FAILED,
            progress=100.0 if success else self._tasks[task_id].progress,
            error=error,
            completed_at=datetime.now(),
        )

        status_str = "completed" if success else f"failed: {error}"
        logger.info(f"Task {task_id} {status_str}")

    def delete_task(self, task_id: str) -> bool:
        if task_id in self._tasks:
            del self._tasks[task_id]
            logger.info(f"Task deleted: {task_id}")
            return True
        return False

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[TaskInfo]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

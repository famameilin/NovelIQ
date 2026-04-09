"""
任务管理器模块

创建时间: 2025-03-11
创建者: TraeAI
任务: 任务管理

修改时间: 2026-04-09
修改者: GLM-5
任务: sse-architecture-review
修改内容:
- threading.Event → asyncio.Event，与异步分析流程语义一致
- cancel_event.is_set() 和 set() 行为保持兼容
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.api.models.responses import TaskStatus
from src.storage.repositories import RunRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class TaskInfo:
    task_id: str
    novel_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    stage: str | None = None
    sub_stage: str | None = None
    current: int = 0
    total: int = 100
    message: str | None = None
    llm_outputs: list[str] = field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any = None
    cancel_event: asyncio.Event | None = None
    asyncio_task: asyncio.Task | None = None


class TaskManager:
    def __init__(self, progress_callback: Callable[[str, str, float, str], None] | None = None):
        self._tasks: dict[str, TaskInfo] = {}
        self._progress_callback = progress_callback
        self._db_session_factory: Callable[[], Session] | None = None

    def set_db_session_factory(self, factory: Callable[[], Session]) -> None:
        """设置数据库会话工厂"""
        self._db_session_factory = factory

    def _update_db(self, task_id: str, **kwargs) -> None:
        """更新数据库中的任务状态"""
        if self._db_session_factory is None:
            return
        try:
            run_repo = RunRepository(self._db_session_factory())
            if "status" in kwargs:
                status = kwargs["status"]
                if isinstance(status, TaskStatus):
                    status = status.value
                run_repo.update_run_status(task_id, status)
            if "progress" in kwargs:
                run_repo.update_run_progress(task_id, kwargs["progress"])
            if "stage" in kwargs:
                run_repo.update_run_stage(task_id, kwargs["stage"])
            logger.debug(f"Task DB updated: {task_id} - {kwargs}")
        except Exception as e:
            logger.warning(f"Failed to update task DB: {e}")

    def create_task(self, task_id: str, novel_id: str) -> TaskInfo:
        task = TaskInfo(
            task_id=task_id,
            novel_id=novel_id,
            status=TaskStatus.PENDING,
            started_at=datetime.now(),
            cancel_event=asyncio.Event(),
        )
        self._tasks[task_id] = task
        logger.info(f"Task created: {task_id} for novel {novel_id}")
        return task

    def get_task(self, task_id: str) -> TaskInfo | None:
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

            if self._progress_callback and "progress" in kwargs:
                self._progress_callback(
                    task_id,
                    kwargs.get("stage", task.stage or ""),
                    kwargs["progress"],
                    kwargs.get("message", ""),
                )

        self._update_db(task_id, **kwargs)

    def complete_task(self, task_id: str, success: bool = True, error: str | None = None) -> None:
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

    def list_tasks(self, status: TaskStatus | None = None) -> list[TaskInfo]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def cancel_task(self, task_id: str) -> bool:
        """设置取消信号，返回 True 表示信号已设置"""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.CANCELLING):
            return False
        task.status = TaskStatus.CANCELLING
        if task.cancel_event:
            task.cancel_event.set()
        logger.info(f"Task {task_id} cancellation requested")
        self._update_db(task_id, status=TaskStatus.CANCELLING)
        return True

    def cancel_completed_task(self, task_id: str, error: str | None = None) -> None:
        """将任务标记为已取消"""
        if task_id not in self._tasks:
            return
        self.update_task(
            task_id,
            status=TaskStatus.CANCELLED,
            error=error,
            completed_at=datetime.now(),
        )
        logger.info(f"Task {task_id} cancelled: {error}")

    def append_llm_output(self, task_id: str, content: str) -> None:
        """追加 LLM 输出到任务信息，限制最大条目数防止内存泄漏。"""
        task = self._tasks.get(task_id)
        if task:
            task.llm_outputs.append(content)
            if len(task.llm_outputs) > 100:
                task.llm_outputs = task.llm_outputs[-100:]

    def store_asyncio_task(self, task_id: str, asyncio_task: asyncio.Task) -> None:
        """保存 asyncio.Task 引用"""
        task_info = self._tasks.get(task_id)
        if task_info:
            task_info.asyncio_task = asyncio_task
            logger.debug(f"Asyncio task stored for {task_id}")

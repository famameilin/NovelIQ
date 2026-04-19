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

    修改时间: 2026-04-19
    修改者: TraeAI
    任务: task-system-db-driven-refactor
    修改内容:
    - 重构 _update_db() 为可靠写入，移除静默失败
    - TaskManager 职责收缩为执行缓存容器，不再承担业务真相判断

    修改时间: 2026-04-19
    修改者: Codex (GPT-5)
    任务: fix-task-system-review-findings
    修改内容: 持久化 message 字段，并在 DB 写入后主动关闭短生命周期 Session
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.api.models.responses import TaskStatus
from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id
from src.storage.repositories import RunRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class TaskInfo:
    """任务执行缓存，仅保留运行时必要的进程级对象。"""

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
    """
    进程级执行缓存容器（非业务真相源）。

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 任务管理

    修改时间: 2026-04-19
    修改者: TraeAI
    任务: task-6-task-manager-responsibility-shrink
    修改内容: 职责收缩为纯执行缓存，移除业务真相判断

    职责边界:
    =========
    属于本类职责:
    - asyncio.Task 对象引用管理（store_asyncio_task）
    - 取消信号传递（cancel_event）
    - SSE 短期输出缓冲（llm_outputs, stage/progress 更新）
    - 创建/删除/更新内存 TaskInfo 对象

    不属于本类职责（由业务层/DB层处理）:
    - 任务存在性判断（应查询数据库）
    - 业务状态合法性判断（如 cancel/delete 前置条件）
    - 任务列表查询（list_tasks/get_tasks_by_novel 已 deprecated）
    - 决定 cancel/resume/delete 操作是否合法

    调用方须知:
    - get_task() 返回"当前进程是否持有该任务的执行缓存"，而非"系统是否存在该任务"
    - 服务重启后，所有任务在 TaskManager 中均不存在，需从 DB 恢复
    - 业务真相唯一来源: 数据库 run 表
    """

    def __init__(self, progress_callback: Callable[[str, str, float, str], None] | None = None):
        self._tasks: dict[str, TaskInfo] = {}
        self._progress_callback = progress_callback
        self._db_session_factory: Callable[[], Session] | None = None

    def set_db_session_factory(self, factory: Callable[[], Session]) -> None:
        """设置数据库会话工厂"""
        self._db_session_factory = factory

    def _update_db(self, task_id: str, **kwargs) -> None:
        """
        可靠地更新数据库中的任务状态。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-system-db-driven-refactor
        说明: 移除静默失败，确保状态变更可靠持久化。DB 为唯一业务真相。
        """
        if self._db_session_factory is None:
            logger.warning(f"DB session factory not set, skipping DB update for task {task_id}")
            return

        # 构建更新参数字典
        update_params: dict[str, Any] = {}
        if "status" in kwargs:
            status = kwargs["status"]
            update_params["status"] = status.value if isinstance(status, TaskStatus) else status
        if "progress" in kwargs:
            update_params["progress"] = kwargs["progress"]
        if "stage" in kwargs:
            update_params["stage"] = kwargs["stage"]
        if "sub_stage" in kwargs:
            update_params["sub_stage"] = kwargs["sub_stage"]
        if "current" in kwargs:
            update_params["current"] = kwargs["current"]
        if "total" in kwargs:
            update_params["total"] = kwargs["total"]
        if "message" in kwargs:
            update_params["message"] = kwargs["message"]
        if "error" in kwargs:
            update_params["error"] = kwargs["error"]
        if "cancel_requested" in kwargs:
            update_params["cancel_requested"] = kwargs["cancel_requested"]
        if "completed_at" in kwargs:
            update_params["completed_at"] = kwargs["completed_at"]

        if not update_params:
            return

        # 可靠写入，失败时向上抛出异常
        session = self._db_session_factory()
        try:
            run_repo = RunRepository(session)
            run_id = self._resolve_run_id_for_db_write(task_id, session)
            if run_repo.get_run(run_id) is None:
                raise RuntimeError(f"Run not found for DB update: task_id={task_id}, run_id={run_id}")
            run_repo.update_run_task_fields(run_id, **update_params)
            logger.debug(f"Task DB updated: task_id={task_id}, run_id={run_id} - {update_params}")
        except Exception as e:
            logger.error(f"Failed to update task DB (task_id={task_id}): {e}")
            raise
        finally:
            session.close()

    def _resolve_run_id_for_db_write(self, task_id: str, session: Session) -> str:
        """
        将任务写回统一解析到真实 run_id。

        创建时间: 2026-04-19
        创建者: Codex (GPT-5)
        任务: fix-task-system-review-findings

        修改时间: 2026-04-19
        修改者: Codex (GPT-5)
        任务: 修复 task_id/run_id 混写
        修改内容: 对 8 位 task_id 先查映射，再按完整 run_id 落库，避免历史 full run_id 任务静默不更新。
        """
        # 历史数据里 run_id 可能是完整 UUID，当前 API 层仍主要传 8 位 task_id。
        # 这里统一先解析成真实 run_id，再进行精确更新，避免 DB-only 状态查询读到旧值。
        if len(task_id) == 8:
            try:
                return task_id_to_run_id(task_id, session)
            except (TaskIDNotFoundError, ValueError) as exc:
                raise RuntimeError(f"Cannot resolve run_id from task_id={task_id}") from exc
        return task_id

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
        """
        查询当前进程是否持有该任务的执行缓存。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-6-task-manager-responsibility-shrink
        说明: 仅回答"当前进程是否有该任务的执行缓存"，不回答"系统是否存在该任务"。
              服务重启后返回 None 是正常行为，调用方应从 DB 查询业务状态。

        Returns:
            TaskInfo 对象（如果进程持有缓存），否则返回 None
        """
        return self._tasks.get(task_id)

    def get_tasks_by_novel(self, novel_id: str) -> list[TaskInfo]:
        """
        已弃用: 业务查询应使用数据库层（NovelService.get_tasks_by_novel）。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-6-task-manager-responsibility-shrink
        说明: 此方法仅返回进程内存中的任务，不代表完整的业务数据。调用方应改用 DB 查询。
        """
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
        """
        更新任务完成状态（仅内存操作）。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-6-task-manager-responsibility-shrink
        修改内容: 仅更新内存状态，不再做任务存在性检查，不再写 DB。
        说明: 业务真相的 status 更新应由调用方直接操作 DB。
        """
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning(f"Task {task_id} not in memory, skipping complete_task")
            return

        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED if success else TaskStatus.FAILED,
            progress=100.0 if success else task.progress,
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
        """
        已弃用: 业务查询应使用数据库层（RunRepository.get_by_status 或类似方法）。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-6-task-manager-responsibility-shrink
        说明: 此方法仅枚举进程内存中的任务，不代表完整的业务数据。调用方应改用 DB 查询。
        """
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def cancel_task(self, task_id: str) -> bool:
        """
        设置取消信号（纯执行层操作）。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-6-task-manager-responsibility-shrink
        修改内容: 移除业务状态合法性判断（已完成/已取消等），调用方应在调用前自行判断。

        说明: 本方法仅负责设置 cancel_event 和同步内存 status，
              不做"是否允许取消"的业务判断。
              DB cancel_requested 写入应由调用方直接操作或通过 _update_db。

        Returns:
            True 表示 cancel_event 已设置，False 表示任务不在内存中
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False

        # 设置内存取消信号（加速缓存）
        task.status = TaskStatus.CANCELLING
        if task.cancel_event:
            task.cancel_event.set()

        logger.info(f"Task {task_id} memory cancel_event set")
        return True

    def cancel_completed_task(self, task_id: str, error: str | None = None) -> None:
        """
        将任务标记为已取消（仅内存操作）。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-6-task-manager-responsibility-shrink
        说明: 仅更新内存状态，业务状态应由调用方写入 DB。
        """
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning(f"Task {task_id} not in memory, skipping cancel_completed_task")
            return

        self.update_task(
            task_id,
            status=TaskStatus.CANCELLED,
            error=error,
            completed_at=datetime.now(),
        )
        logger.info(f"Task {task_id} memory status set to CANCELLED")

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

"""
任务管理器模块
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.api.services.task_runtime_persistence_service import TaskRuntimePersistenceService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class TaskInfo:
    """任务执行缓存，仅保留进程级执行对象和短期输出缓冲
    """

    task_id: str
    llm_outputs: list[str] = field(default_factory=list)
    cancel_event: asyncio.Event | None = None
    asyncio_task: asyncio.Task | None = None
    heartbeat_stop_event: asyncio.Event | None = None
    heartbeat_task: asyncio.Task | None = None


class TaskManager:
    """
    进程级执行缓存容器（非业务真相源）

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
    - 任务列表查询（应直接查询数据库）
    - 决定 cancel/resume/delete 操作是否合法

    调用方须知:
    - get_task() 返回"当前进程是否持有该任务的执行缓存"，而非"系统是否存在该任务"
    - 服务重启后，所有任务在 TaskManager 中均不存在，需从 DB 恢复
    - 业务真相唯一来源: 数据库 run 表
    """

    def __init__(
        self,
        progress_callback: Callable[[str, str, float, str], None] | None = None,
        worker_id: str | None = None,
        heartbeat_interval_seconds: float = 30.0,
    ):
        """
        初始化任务执行缓存管理器
        """
        self._tasks: dict[str, TaskInfo] = {}
        self._progress_callback = progress_callback
        self._worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._runtime_persistence = TaskRuntimePersistenceService(self._worker_id)

    def set_db_session_factory(self, factory: Callable[[], Session]) -> None:
        """
        设置数据库会话工厂
        """
        self._runtime_persistence.set_session_factory(factory)

    def get_worker_id(self) -> str:
        """
        返回当前进程的稳定 worker_id
        """
        return self._worker_id

    def _update_db(self, task_id: str, **kwargs) -> None:
        """
        可靠地更新数据库中的任务状态

        说明: 移除静默失败，确保状态变更可靠持久化。DB 为唯一业务真相
        """
        self._runtime_persistence.update_task_runtime(task_id, **kwargs)

    def _should_refresh_worker_heartbeat(self, update_params: dict[str, Any]) -> bool:
        """
        判断本次写回是否应刷新 worker 归属和心跳
        """
        return self._runtime_persistence._should_refresh_worker_heartbeat(update_params)

    def _resolve_run_id_for_db_write(self, task_id: str, session: Session) -> str:
        """
        将任务写回统一解析到真实 run_id
        """
        return self._runtime_persistence._resolve_run_id_for_db_write(task_id, session)

    def create_task(self, task_id: str, novel_id: str) -> TaskInfo:
        """创建任务的内存执行缓存
        """
        task = TaskInfo(
            task_id=task_id,
            cancel_event=asyncio.Event(),
            heartbeat_stop_event=asyncio.Event(),
        )
        self._tasks[task_id] = task
        logger.info(f"Task created: {task_id} for novel {novel_id}")
        return task

    def get_task(self, task_id: str) -> TaskInfo | None:
        """
        查询当前进程是否持有该任务的执行缓存

        说明: 仅回答"当前进程是否有该任务的执行缓存"，不回答"系统是否存在该任务"
              服务重启后返回 None 是正常行为，调用方应从 DB 查询业务状态

        Returns:
            TaskInfo 对象（如果进程持有缓存），否则返回 None
        """
        return self._tasks.get(task_id)

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
                    kwargs.get("stage", ""),
                    kwargs["progress"],
                    kwargs.get("message", ""),
                )
        else:
            logger.warning(
                f"Task {task_id} not in memory cache, updating DB only. "
                f"This may indicate a stale cache or external state transition. Update params: {kwargs}"
            )

        self._update_db(task_id, **kwargs)

    def complete_task(self, task_id: str, success: bool = True, error: str | None = None) -> None:
        """
        更新任务完成状态的内存缓存（仅内存操作）
        """
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning(f"Task {task_id} not in memory, skipping complete_task")
            return

        self._stop_runtime_heartbeat(task_id)

        status_str = "completed" if success else f"failed: {error}"
        logger.info(f"Task {task_id} {status_str}")

    def delete_task(self, task_id: str) -> bool:
        if task_id in self._tasks:
            self._stop_runtime_heartbeat(task_id)
            del self._tasks[task_id]
            logger.info(f"Task deleted: {task_id}")
            return True
        return False

    def cancel_task(self, task_id: str) -> bool:
        """
        设置取消信号（纯执行层操作）

        说明: 本方法仅负责设置 cancel_event，不做"是否允许取消"的业务判断

        Returns:
            True 表示 cancel_event 已设置，False 表示任务不在内存中
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False

        if task.cancel_event:
            task.cancel_event.set()

        logger.info(f"Task {task_id} memory cancel_event set")
        return True

    def cancel_completed_task(self, task_id: str, error: str | None = None) -> None:
        """
        清理任务的内存执行缓存并停止心跳（仅内存操作）
        """
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning(f"Task {task_id} not in memory, skipping cancel_completed_task")
            return

        self._stop_runtime_heartbeat(task_id)

        logger.info(f"Task {task_id} memory cache cleaned for cancellation")

    def append_llm_output(self, task_id: str, content: str) -> None:
        """追加 LLM 输出到任务信息，限制最大条目数防止内存泄漏"""
        task = self._tasks.get(task_id)
        if task:
            task.llm_outputs.append(content)
            if len(task.llm_outputs) > 100:
                task.llm_outputs = task.llm_outputs[-100:]

    def store_asyncio_task(self, task_id: str, asyncio_task: asyncio.Task) -> None:
        """
        保存 asyncio.Task 引用并启动独立心跳
        """
        task_info = self._tasks.get(task_id)
        if task_info:
            task_info.asyncio_task = asyncio_task
            self._start_runtime_heartbeat(task_id)
            logger.debug(f"Asyncio task stored for {task_id}")

    def _start_runtime_heartbeat(self, task_id: str) -> None:
        """
        为当前运行任务启动独立心跳协程

        说明: 心跳与阶段进度写回解耦，保证长阶段静默执行时也能持续刷新 heartbeat_at
        """
        task_info = self._tasks.get(task_id)
        if task_info is None:
            return

        if task_info.heartbeat_task and not task_info.heartbeat_task.done():
            return

        stop_event = task_info.heartbeat_stop_event
        if stop_event is None or stop_event.is_set():
            stop_event = asyncio.Event()
            task_info.heartbeat_stop_event = stop_event

        heartbeat_task = asyncio.create_task(self._runtime_heartbeat_loop(task_id, stop_event))
        task_info.heartbeat_task = heartbeat_task
        heartbeat_task.add_done_callback(lambda finished_task: self._handle_heartbeat_task_done(task_id, finished_task))

    def _stop_runtime_heartbeat(self, task_id: str) -> None:
        """
        停止任务心跳协程

        说明: 在任务成功/失败/取消/删除时及时停止 heartbeat，避免终态后继续刷新 liveness
        """
        task_info = self._tasks.get(task_id)
        if task_info is None:
            return

        if task_info.heartbeat_stop_event and not task_info.heartbeat_stop_event.is_set():
            task_info.heartbeat_stop_event.set()
        if task_info.heartbeat_task and not task_info.heartbeat_task.done():
            task_info.heartbeat_task.cancel()

    async def _runtime_heartbeat_loop(self, task_id: str, stop_event: asyncio.Event) -> None:
        """
        周期性刷新活跃任务的 worker 心跳

        说明: 即使阶段内部长时间没有 progress 事件，也要持续写回 heartbeat_at
        """
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._heartbeat_interval_seconds)
                break
            except TimeoutError:
                pass

            task_info = self._tasks.get(task_id)
            if task_info is None:
                break

            runtime_task = task_info.asyncio_task
            if runtime_task is None or runtime_task.done():
                break

            try:
                # heartbeat 独立于 progress/message 写回，专门用于表示“这个进程仍然活着并持有执行权”
                # 2026-08-13 P2：列无时区，统一落 naive UTC 挂钟（避免 PG 会话时区转换错位）
                self._update_db(
                    task_id,
                    worker_id=self._worker_id,
                    heartbeat_at=datetime.now(UTC).replace(tzinfo=None),
                )
            except Exception as exc:
                logger.error(f"Failed to refresh runtime heartbeat for task {task_id}: {exc}")

    def _handle_heartbeat_task_done(self, task_id: str, heartbeat_task: asyncio.Task) -> None:
        """
        收尾 heartbeat 协程并记录异常

        说明: 避免 heartbeat 后台任务异常结束后只留下未观察到的 Task exception
        """
        task_info = self._tasks.get(task_id)
        if task_info and task_info.heartbeat_task is heartbeat_task:
            task_info.heartbeat_task = None

        try:
            heartbeat_task.result()
        except asyncio.CancelledError:
            logger.debug(f"Runtime heartbeat stopped for task {task_id}")
        except Exception as exc:
            logger.error(f"Runtime heartbeat crashed for task {task_id}: {exc}")

    async def shutdown(self) -> None:
        """
        回收当前进程 TaskManager 持有的执行缓存与后台任务
        """

        task_ids = list(self._tasks.keys())
        running_tasks: list[asyncio.Task] = []
        for task_id in task_ids:
            task_info = self._tasks.get(task_id)
            if task_info is None:
                continue

            if task_info.cancel_event is not None and not task_info.cancel_event.is_set():
                task_info.cancel_event.set()
            self._stop_runtime_heartbeat(task_id)

            if task_info.asyncio_task is not None and not task_info.asyncio_task.done():
                task_info.asyncio_task.cancel()
                running_tasks.append(task_info.asyncio_task)

        if running_tasks:
            await asyncio.gather(*running_tasks, return_exceptions=True)

        self._tasks.clear()

    def reset_for_testing(self) -> None:
        """
        为测试夹具同步清空执行缓存
        """

        task_ids = list(self._tasks.keys())
        for task_id in task_ids:
            task_info = self._tasks.get(task_id)
            if task_info is None:
                continue

            if task_info.cancel_event is not None and not task_info.cancel_event.is_set():
                task_info.cancel_event.set()
            self._stop_runtime_heartbeat(task_id)
            if task_info.asyncio_task is not None and not task_info.asyncio_task.done():
                task_info.asyncio_task.cancel()

        self._tasks.clear()

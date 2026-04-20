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
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.api.models.responses import TaskStatus
from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id
from src.storage.repositories import RunRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class TaskInfo:
    """任务执行缓存，仅保留进程级执行对象和短期输出缓冲。

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 任务管理

    修改时间: 2026-04-20
    修改者: TraeAI
    任务: task-system-db-driven-refactor
    修改内容: 剥离业务状态字段（status/progress/stage/sub_stage/current/total/message/error/completed_at/novel_id），
              仅保留 asyncio.Task、cancel_event、heartbeat 对象和 llm_outputs 短期缓冲。
              业务真相统一由 DB 提供，内存不承担状态判断职责。
    """

    task_id: str
    llm_outputs: list[str] = field(default_factory=list)
    cancel_event: asyncio.Event | None = None
    asyncio_task: asyncio.Task | None = None
    heartbeat_stop_event: asyncio.Event | None = None
    heartbeat_task: asyncio.Task | None = None


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
        初始化任务执行缓存管理器。

        修改时间: 2026-04-20
        修改者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        修改内容: 为当前进程生成稳定 worker_id，后续所有运行态写回都会带上 worker 归属与心跳。
        """
        self._tasks: dict[str, TaskInfo] = {}
        self._progress_callback = progress_callback
        self._db_session_factory: Callable[[], Session] | None = None
        self._worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self._heartbeat_interval_seconds = heartbeat_interval_seconds

    def set_db_session_factory(self, factory: Callable[[], Session]) -> None:
        """设置数据库会话工厂"""
        self._db_session_factory = factory

    def get_worker_id(self) -> str:
        """
        返回当前进程的稳定 worker_id。

        创建时间: 2026-04-20
        创建者: Codex (GPT-5)
        任务: fix-pending-task-pickup
        修改内容: 为 DB claim / startup recovery 提供统一 worker 标识读取入口。
        """
        return self._worker_id

    def _update_db(self, task_id: str, **kwargs) -> None:
        """
        可靠地更新数据库中的任务状态。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-system-db-driven-refactor

        修改时间: 2026-04-20
        修改者: TraeAI
        任务: task-system-db-driven-refactor
        修改内容: 明确枚举→字符串转换约定。kwargs 中的 TaskStatus 枚举值会自动转为 .value 字符串，
                  与 DB 字段类型一致。调用方混用枚举和字符串时，此处统一处理。

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
        if "worker_id" in kwargs:
            update_params["worker_id"] = kwargs["worker_id"]
        if "heartbeat_at" in kwargs:
            update_params["heartbeat_at"] = kwargs["heartbeat_at"]

        if self._should_refresh_worker_heartbeat(update_params):
            # 中文注释：只要任务仍由本进程活跃推进，就持续刷新 worker 归属和心跳，
            # 这样启动恢复才能准确识别“这个进程留下来的孤儿任务”。
            update_params.setdefault("worker_id", self._worker_id)
            update_params["heartbeat_at"] = datetime.now(UTC)

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

    def _should_refresh_worker_heartbeat(self, update_params: dict[str, Any]) -> bool:
        """
        判断本次写回是否应刷新 worker 归属和心跳。

        创建时间: 2026-04-20
        创建者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        修改内容: 仅在活跃运行态写回时注入 worker_id/heartbeat_at，避免终态字段误刷新心跳。
        """
        active_statuses = {
            TaskStatus.PENDING.value,
            TaskStatus.RUNNING.value,
            TaskStatus.CANCELLING.value,
        }
        tracked_runtime_fields = {"progress", "stage", "sub_stage", "current", "total", "message"}

        status = update_params.get("status")
        if status in active_statuses:
            return True

        return any(field in update_params for field in tracked_runtime_fields)

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
        """创建任务的内存执行缓存。

        修改时间: 2026-04-20
        修改者: TraeAI
        任务: task-system-db-driven-refactor
        修改内容: 不再初始化业务状态字段（status/progress/novel_id 等），仅创建执行缓存对象。
                  novel_id 仅用于日志记录，不再存储到 TaskInfo 中。
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
        更新任务完成状态的内存缓存（仅内存操作）。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-6-task-manager-responsibility-shrink

        修改时间: 2026-04-20
        修改者: TraeAI
        任务: task-system-db-driven-refactor
        修改内容: 改为仅更新内存状态并停止心跳，不再写 DB。业务真相的 status 更新应由调用方直接操作 DB。
        说明: 调用方需确保已自行完成 DB 终态写入。
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
        设置取消信号（纯执行层操作）。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-6-task-manager-responsibility-shrink
        修改内容: 移除业务状态合法性判断（已完成/已取消等），调用方应在调用前自行判断。

        修改时间: 2026-04-20
        修改者: TraeAI
        任务: task-system-db-driven-refactor
        修改内容: 不再修改内存 status 字段（TaskInfo 已无 status），仅设置 cancel_event。
                  DB cancel_requested 写入由调用方直接操作。

        说明: 本方法仅负责设置 cancel_event，不做"是否允许取消"的业务判断。

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
        清理任务的内存执行缓存并停止心跳（仅内存操作）。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-6-task-manager-responsibility-shrink

        修改时间: 2026-04-20
        修改者: TraeAI
        任务: task-system-db-driven-refactor
        修改内容: 改为仅停止心跳并清理内存缓存，不再写 DB。业务状态应由调用方写入 DB。
        """
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning(f"Task {task_id} not in memory, skipping cancel_completed_task")
            return

        self._stop_runtime_heartbeat(task_id)

        logger.info(f"Task {task_id} memory cache cleaned for cancellation")

    def append_llm_output(self, task_id: str, content: str) -> None:
        """追加 LLM 输出到任务信息，限制最大条目数防止内存泄漏。"""
        task = self._tasks.get(task_id)
        if task:
            task.llm_outputs.append(content)
            if len(task.llm_outputs) > 100:
                task.llm_outputs = task.llm_outputs[-100:]

    def store_asyncio_task(self, task_id: str, asyncio_task: asyncio.Task) -> None:
        """
        保存 asyncio.Task 引用并启动独立心跳。

        修改时间: 2026-04-20
        修改者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        修改内容: 为长时间无进度事件的运行阶段增加独立 heartbeat，避免启动恢复误判活跃任务为 orphan。
        """
        task_info = self._tasks.get(task_id)
        if task_info:
            task_info.asyncio_task = asyncio_task
            self._start_runtime_heartbeat(task_id)
            logger.debug(f"Asyncio task stored for {task_id}")

    def _start_runtime_heartbeat(self, task_id: str) -> None:
        """
        为当前运行任务启动独立心跳协程。

        创建时间: 2026-04-20
        创建者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        说明: 心跳与阶段进度写回解耦，保证长阶段静默执行时也能持续刷新 heartbeat_at。
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
        停止任务心跳协程。

        创建时间: 2026-04-20
        创建者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        说明: 在任务成功/失败/取消/删除时及时停止 heartbeat，避免终态后继续刷新 liveness。
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
        周期性刷新活跃任务的 worker 心跳。

        创建时间: 2026-04-20
        创建者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        说明: 即使阶段内部长时间没有 progress 事件，也要持续写回 heartbeat_at。
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
                # 中文注释：heartbeat 独立于 progress/message 写回，专门用于表示“这个进程仍然活着并持有执行权”。
                self._update_db(task_id, worker_id=self._worker_id, heartbeat_at=datetime.now(UTC))
            except Exception as exc:
                logger.error(f"Failed to refresh runtime heartbeat for task {task_id}: {exc}")

    def _handle_heartbeat_task_done(self, task_id: str, heartbeat_task: asyncio.Task) -> None:
        """
        收尾 heartbeat 协程并记录异常。

        创建时间: 2026-04-20
        创建者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        说明: 避免 heartbeat 后台任务异常结束后只留下未观察到的 Task exception。
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

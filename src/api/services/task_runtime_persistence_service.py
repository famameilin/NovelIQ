"""
任务运行态持久化服务

说明: 将 TaskManager 的 DB 写回、run_id 解析与 worker heartbeat 刷新逻辑收口到独立服务
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from src.api.models.responses import TaskStatus
from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id
from src.storage.repositories import RunRepository


class TaskRuntimePersistenceService:
    """
    任务运行态持久化服务
    """

    def __init__(self, worker_id: str) -> None:
        """
        初始化运行态持久化服务
        """
        self._worker_id = worker_id
        self._session_factory = None

    def set_session_factory(self, factory) -> None:
        """
        设置数据库会话工厂
        """
        self._session_factory = factory

    def update_task_runtime(self, task_id: str, **kwargs) -> None:
        """
        可靠地更新数据库中的任务运行态
        """
        if self._session_factory is None:
            logger.warning(f"DB session factory not set, skipping DB update for task {task_id}")
            return

        update_params = self._build_update_params(kwargs)
        if self._should_refresh_worker_heartbeat(update_params):
            # 只要任务仍由本进程活跃推进，就持续刷新 worker 归属和心跳，
            # 这样启动恢复才能准确识别“这个进程留下来的孤儿任务”
            update_params.setdefault("worker_id", self._worker_id)
            update_params["heartbeat_at"] = datetime.now(UTC)

        if not update_params:
            return

        session = self._session_factory()
        try:
            run_repo = RunRepository(session)
            run_id = self._resolve_run_id_for_db_write(task_id, session)
            if run_repo.get_run(run_id) is None:
                raise RuntimeError(f"Run not found for DB update: task_id={task_id}, run_id={run_id}")
            run_repo.update_run_task_fields(run_id, **update_params)
            logger.debug(f"Task DB updated: task_id={task_id}, run_id={run_id} - {update_params}")
        except Exception as exc:
            logger.error(f"Failed to update task DB (task_id={task_id}): {exc}")
            raise
        finally:
            session.close()

    def _build_update_params(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """
        将调用方 kwargs 规整为 repository 可接受的更新参数
        """
        update_params: dict[str, Any] = {}
        if "status" in kwargs:
            status = kwargs["status"]
            update_params["status"] = status.value if isinstance(status, TaskStatus) else status
        for field in (
            "progress",
            "stage",
            "sub_stage",
            "current",
            "total",
            "message",
            "error",
            "cancel_requested",
            "completed_at",
            "worker_id",
            "heartbeat_at",
        ):
            if field in kwargs:
                update_params[field] = kwargs[field]
        return update_params

    def _should_refresh_worker_heartbeat(self, update_params: dict[str, Any]) -> bool:
        """
        判断本次写回是否应刷新 worker 归属和心跳
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

    def _resolve_run_id_for_db_write(self, task_id: str, session) -> str:
        """
        将任务写回统一解析到真实 run_id
        """
        if len(task_id) == 8:
            try:
                return task_id_to_run_id(task_id, session)
            except (TaskIDNotFoundError, ValueError) as exc:
                raise RuntimeError(f"Cannot resolve run_id from task_id={task_id}") from exc
        return task_id

"""
任务应用服务

说明: 将 analysis 路由中的取消、删除、恢复状态机下沉到 service 层，
      让 route 只保留 HTTP 参数绑定与响应装配职责
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from src.storage import get_storage_factory
from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id
from src.work.task_manager import TaskManager
from src.workflows.exceptions import NovelNotFoundError, TaskApplicationError
from src.workflows.service import AnalysisService
from src.workflows.tasks import TaskService


def resolve_task_for_novel(task_service: TaskService, novel_id: str, task_id: str) -> dict[str, Any]:
    """
    获取并校验任务是否属于指定小说
    """
    try:
        task = task_service.get_task(task_id)
    except NovelNotFoundError:
        raise TaskApplicationError(reason="missing_task", message="任务不存在") from None
    if task.get("novel_id") != novel_id:
        raise TaskApplicationError(reason="invalid_state", message="任务不属于该小说")
    return task


def raise_cancel_not_allowed(task_status: str) -> None:
    """
    统一校验任务是否允许进入取消流程
    """
    if task_status in ("completed", "cancelled", "cancelling"):
        raise TaskApplicationError(reason="invalid_state", message=f"任务已{task_status}，无需取消")
    if task_status == "failed":
        raise TaskApplicationError(reason="invalid_state", message="任务已失败，无法取消")


def persist_task_cancellation_request(task_id: str) -> str:
    """
    将取消请求可靠写入数据库
    """
    session_factory = get_storage_factory()
    try:
        session = session_factory()
        run_id = task_id_to_run_id(task_id, session)
        run_repo = session.runs
        latest_status = run_repo.request_task_cancellation(run_id)
        if latest_status is None:
            raise TaskApplicationError(reason="persistence_failed", message="任务取消持久化失败，请稍后重试")
        return latest_status
    except (TaskIDNotFoundError, ValueError) as exc:
        logger.error(f"Task {task_id} run_id not found when persisting cancellation request: {exc}")
        raise TaskApplicationError(reason="persistence_failed", message="任务取消持久化失败，请稍后重试") from exc
    except Exception as exc:
        logger.error(f"Failed to persist cancellation request for task {task_id}: {exc}")
        raise TaskApplicationError(reason="persistence_failed", message="任务取消持久化失败，请稍后重试") from exc


def cancel_unclaimed_pending_task(task_id: str) -> bool:
    """
    直接终结尚未被任何 worker 领取的 pending 任务
    """
    session_factory = get_storage_factory()
    try:
        session = session_factory()
        run_id = task_id_to_run_id(task_id, session)
        run_repo = session.runs
        cancelled = run_repo.cancel_unclaimed_pending_run(run_id, message="任务在启动前已取消")
        pass
        return cancelled
    except (TaskIDNotFoundError, ValueError) as exc:
        logger.error(f"Task {task_id} run_id not found when cancelling unclaimed pending task: {exc}")
        raise TaskApplicationError(reason="persistence_failed", message="任务取消持久化失败，请稍后重试") from exc
    except Exception as exc:
        logger.error(f"Failed to cancel unclaimed pending task {task_id}: {exc}")
        raise TaskApplicationError(reason="persistence_failed", message="任务取消持久化失败，请稍后重试") from exc


async def cleanup_task_runtime_before_delete(task_id: str, task_manager: TaskManager) -> None:
    """
    删除任务前清理运行态缓存与后台协程
    """
    task_info = task_manager.get_task(task_id)
    if task_info is None:
        return
    task_manager.cancel_task(task_id)
    session_factory = get_storage_factory()
    try:
        session = session_factory()
        run_id = task_id_to_run_id(task_id, session)
        run_repo = session.runs
        latest_status = run_repo.request_task_cancellation(run_id)
        if latest_status is None:
            logger.warning(f"Task {task_id} missing from DB during delete cleanup, skipping cancel persistence")
        elif latest_status != "cancelling":
            logger.info(
                "Task "
                f"{task_id}"
                " DB already in terminal state "
                f"{latest_status}"
                " during delete cleanup; skipping cancel persistence"
            )
    except (TaskIDNotFoundError, ValueError):
        logger.warning(f"Task {task_id} run_id not found, skipping run table cancel_requested update")
    except Exception as exc:
        logger.warning(f"Failed to update cancel_requested for task {task_id}: {exc}")
    if task_info.asyncio_task and (not task_info.asyncio_task.done()):
        task_info.asyncio_task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(task_info.asyncio_task, return_exceptions=True), timeout=5.0)
        except TimeoutError:
            logger.warning(f"Delete task: task {task_id} cancel timed out, background coroutine may still be running")
        except Exception as exc:
            logger.warning(f"Delete task: unexpected error cancelling task {task_id}: {exc}")


class TaskApplicationService:
    """
    任务应用服务

    说明: 面向 API 编排任务恢复、取消、删除等跨 DB/运行态的流程
    """

    def __init__(self, task_service: TaskService, task_manager: TaskManager):
        """
        初始化任务应用服务
        """
        self.task_service = task_service
        self.task_manager = task_manager
        self.analysis_service = AnalysisService(task_service, task_manager)

    async def resume_task(self, novel_id: str, task_id: str) -> str:
        """
        继续执行指定任务
        """
        try:
            return await self.analysis_service.resume_task(novel_id, task_id)
        except ValueError as exc:
            raise TaskApplicationError(reason="invalid_state", message=str(exc)) from exc

    async def delete_task(self, novel_id: str, task_id: str) -> dict[str, str]:
        """
        删除单个分析任务
        """
        task = resolve_task_for_novel(self.task_service, novel_id, task_id)
        task_status = task.get("status", "")
        if task_status in ("pending", "running", "cancelling"):
            raise TaskApplicationError(reason="invalid_state", message=f"任务正在{task_status}中，请先取消任务后再删除")
        await cleanup_task_runtime_before_delete(task_id, self.task_manager)
        self.task_service.delete_task(task_id, task_manager=self.task_manager)
        return {"message": "任务删除成功", "novel_id": novel_id, "task_id": task_id}

    def delete_tasks_for_novel(self, novel_id: str) -> int:
        """
        删除小说下全部任务（含运行态清理）

        说明: 小说级删除的前置条件是任务不在飞——ensure_tasks_deletable 会拒绝运行态任务；
        因此这里无需（也无法）做异步中断。返回删除的任务数。
        """
        runs = self.task_service.collect_runs(novel_id)
        self.task_service.ensure_tasks_deletable(novel_id, runs)
        for run in runs:
            task_id = str(run["task_id"])
            self.task_service.delete_task(task_id, task_manager=self.task_manager)
        return len(runs)

    async def cancel_task(self, novel_id: str, task_id: str) -> dict[str, str]:
        """
        取消指定分析任务
        """
        task = resolve_task_for_novel(self.task_service, novel_id, task_id)
        task_status = task.get("status", "")
        raise_cancel_not_allowed(task_status)
        task_info = self.task_manager.get_task(task_id)
        if task_status == "pending" and task_info is None:
            cancelled = cancel_unclaimed_pending_task(task_id)
            if cancelled:
                logger.info(f"Task {task_id} cancelled immediately before any worker claim")
                return {"task_id": task_id, "status": "cancelled", "message": "任务尚未启动，已直接取消"}
            task = resolve_task_for_novel(self.task_service, novel_id, task_id)
            task_status = task.get("status", "")
            raise_cancel_not_allowed(task_status)
        latest_status = persist_task_cancellation_request(task_id)
        if latest_status != "cancelling":
            raise_cancel_not_allowed(latest_status)
            raise TaskApplicationError(
                reason="invalid_state", message=f"任务状态为 {latest_status}，取消请求未生效，请重试"
            )
        cancelled = self.task_manager.cancel_task(task_id)
        if cancelled:
            return {
                "task_id": task_id,
                "status": "cancelling",
                "message": "已停止派发并立即中断在飞执行，未完成的 work 不保存",
            }
        if task_status in ("pending", "running"):
            logger.info(
                "Task {} cancellation requested (not in memory), DB cancel_requested=true and status=cancelling",
                task_id,
            )
            return {"task_id": task_id, "status": "cancelling", "message": "取消已落库，执行方将立即中断在飞执行"}
        raise TaskApplicationError(reason="invalid_state", message=f"任务状态为 {task_status}，无法取消")

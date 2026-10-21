"""
任务应用服务

说明: 将 analysis 路由中的取消、删除、恢复状态机下沉到 service 层，
      让 route 只保留 HTTP 参数绑定与响应装配职责
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.storage import get_storage_factory
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


async def cleanup_task_runtime_before_delete(task_id: str, task_manager: TaskManager) -> None:
    "删除前等待当前执行对象退出"
    item = task_manager.get_task(task_id)
    if item and item.asyncio_task and not item.asyncio_task.done():
        item.asyncio_task.cancel()
        await asyncio.wait_for(asyncio.gather(item.asyncio_task, return_exceptions=True), timeout=5)


class TaskApplicationService:
    """
    任务应用服务

    说明: 面向 API 编排任务恢复、取消、删除等跨 DB/运行态的流程
    """

    def __init__(
        self, task_service: TaskService, task_manager: TaskManager, analysis_service: AnalysisService | None = None
    ):
        """
        初始化任务应用服务
        """
        self.task_service = task_service
        self.task_manager = task_manager
        self.analysis_service = analysis_service or AnalysisService(task_service, task_manager)

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
        "直接取消当前进程的任务或终止待执行任务"
        task = resolve_task_for_novel(self.task_service, novel_id, task_id)
        raise_cancel_not_allowed(task["status"])
        from src.workflows.progress import AnalysisEventBus

        notifier = AnalysisEventBus(task_id, run_id=task["run_id"], bus=self.analysis_service.bus)
        if task["status"] == "pending":
            if not get_storage_factory()().runs.cancel_pending_run(task["run_id"]):
                current = resolve_task_for_novel(self.task_service, novel_id, task_id)
                raise_cancel_not_allowed(current["status"])
                if current["status"] != "running":
                    raise TaskApplicationError(reason="invalid_state", message="任务状态已变化")
                return await self.cancel_task(novel_id, task_id)
            self.task_manager.cancel_task(task_id)
            await notifier.emit_task_cancelled()
            return {"task_id": task_id, "status": "cancelled"}
        item = self.task_manager.get_task(task_id)
        if not item or not item.asyncio_task or item.asyncio_task.done():
            raise TaskApplicationError(reason="invalid_state", message="当前进程没有该任务的执行对象")
        await notifier.notify("task_state", {"status": "cancelling"})
        item.asyncio_task.cancel()
        await asyncio.gather(item.asyncio_task, return_exceptions=True)
        return {"task_id": task_id, "status": "cancelled"}

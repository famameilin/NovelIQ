"""启动时的运行态收口（运行域）

说明: 进程重启后 running/cancelling 都只活在内存里（任务缓存与 work 队列均为内存态，
      没有租约也没有半成品持久态），因此重启一律收口：running → failed、cancelling →
      cancelled；DB 里可恢复的 pending 任务重新接回执行器。

前提是单实例部署——将来两个进程共库时，新进程会终结旧进程正在跑的任务。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.storage import get_storage

if TYPE_CHECKING:
    from src.work.task_manager import TaskManager
    from src.workflows.service import AnalysisService
    from src.workflows.tasks import TaskService


def recover_orphaned_runs() -> tuple[int, int]:
    """收口上次进程遗留的运行中任务

    Returns:
        tuple[int, int]: (failed_count, cancelled_count)
    """
    session = get_storage()
    repo = session.runs
    failed_count = repo.mark_running_as_failed()
    cancelled_count = repo.mark_cancelling_as_cancelled()
    return (failed_count, cancelled_count)


async def resume_pending_tasks(task_service: TaskService, task_manager: TaskManager) -> tuple[int, int]:
    """把 DB 中可恢复的 pending 任务重新接回执行器

    Returns:
        tuple[int, int]: (scheduled_count, cancelled_count)
    """
    from src.workflows.service import AnalysisService

    service: AnalysisService = AnalysisService(task_service, task_manager)
    return await service.recover_pending_tasks()
